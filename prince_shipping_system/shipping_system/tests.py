import csv
import io
import os
import shutil
import tempfile
import zipfile
from datetime import datetime, date

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from openpyxl import load_workbook

from .models import TruckShipment, ShipmentStatusEvent


def _uploaded(name: str, content: bytes = b'test') -> SimpleUploadedFile:
	return SimpleUploadedFile(name, content, content_type='application/octet-stream')


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix='smartfiling_test_media_'))
class ClearanceWorkflowTests(TestCase):
	@classmethod
	def tearDownClass(cls):
		# MEDIA_ROOT is applied via override_settings, so read from settings at runtime
		from django.conf import settings

		path = getattr(settings, 'MEDIA_ROOT', None)
		super().tearDownClass()
		if path and os.path.isdir(path):
			shutil.rmtree(path, ignore_errors=True)

	def setUp(self):
		self.user = User.objects.create_user(username='tester', password='pass12345')
		self.client.force_login(self.user)

	def _create_stage1_shipment(self, **kwargs) -> TruckShipment:
		defaults = {
			'truck_registration': 'TRUCK 1',
			'container_number': 'CONT/123',
			'bill_of_lading_number': 'BOL-001',
			'manifest_number': 'MAN-001',
			'weight_kg': '123.45',
			'eta_date': date(2026, 3, 1),
			'duty_calculation_amount': '100.00',
			'status': TruckShipment.Status.NOT_REGISTERED,
		}
		defaults.update(kwargs)
		return TruckShipment.objects.create(**defaults)

	def test_stage1_required_uploads_complete_property(self):
		s = self._create_stage1_shipment()
		self.assertFalse(s.stage1_required_uploads_complete)
		s.packing_list_file = _uploaded('packing.pdf')
		s.invoice_file = _uploaded('invoice.pdf')
		s.importer_tax_clearance_file = _uploaded('tax.pdf')
		s.save()
		s.refresh_from_db()
		self.assertTrue(s.stage1_required_uploads_complete)

	def test_create_shipment_allows_blank_truck_registration_and_container_number(self):
		url = reverse('add_shipment')
		resp = self.client.post(
			url,
			data={
				'truck_registration': '',
				'container_number': '',
				'bill_of_lading_number': '',
				'manifest_number': '',
				'weight_kg': '',
				'eta_date': '',
				'duty_calculation_amount': '',
			},
			**{'HTTP_HX_REQUEST': 'true', 'HTTP_HX_TARGET': 'modal-body'},
		)
		self.assertEqual(resp.status_code, 204)
		self.assertEqual(TruckShipment.objects.count(), 1)
		s = TruckShipment.objects.first()
		assert s is not None
		self.assertEqual(s.status, TruckShipment.Status.NOT_REGISTERED)
		self.assertEqual(s.truck_registration, '')
		self.assertEqual(s.container_number, '')
		self.assertEqual(s.bill_of_lading_number, '')
		self.assertEqual(s.manifest_number, '')
		self.assertIsNone(s.weight_kg)
		self.assertIsNone(s.eta_date)
		self.assertIsNone(s.duty_calculation_amount)

	def test_transition_stage1_requires_bol_manifest_weight_eta_and_duty(self):
		s = self._create_stage1_shipment(
			truck_registration='TRUCK 1',
			bill_of_lading_number='',
			manifest_number='',
			weight_kg=None,
			eta_date=None,
			duty_calculation_amount=None,
		)
		s.packing_list_file = _uploaded('packing.pdf')
		s.invoice_file = _uploaded('invoice.pdf')
		s.importer_tax_clearance_file = _uploaded('tax.pdf')
		s.save()

		url = reverse('shipment_transition', args=[s.id])
		resp = self.client.post(
			url,
			data={'to_status': TruckShipment.Status.REGISTERED},
			**{'HTTP_HX_REQUEST': 'true', 'HTTP_HX_TARGET': 'modal-body'},
		)
		self.assertEqual(resp.status_code, 400)
		s.refresh_from_db()
		self.assertEqual(s.status, TruckShipment.Status.NOT_REGISTERED)

	def test_transition_stage1_requires_three_mandatory_docs(self):
		s = self._create_stage1_shipment()
		url = reverse('shipment_transition', args=[s.id])

		# Missing docs -> blocked
		resp = self.client.post(
			url,
			data={'to_status': TruckShipment.Status.REGISTERED},
			**{'HTTP_HX_REQUEST': 'true', 'HTTP_HX_TARGET': 'modal-body'},
		)
		self.assertEqual(resp.status_code, 400)
		s.refresh_from_db()
		self.assertEqual(s.status, TruckShipment.Status.NOT_REGISTERED)

		# Add mandatory docs -> allowed
		s.packing_list_file = _uploaded('packing.pdf')
		s.invoice_file = _uploaded('invoice.pdf')
		s.importer_tax_clearance_file = _uploaded('tax.pdf')
		s.save()

		resp2 = self.client.post(
			url,
			data={'to_status': TruckShipment.Status.REGISTERED},
			**{'HTTP_HX_REQUEST': 'true', 'HTTP_HX_TARGET': 'modal-body'},
		)
		self.assertEqual(resp2.status_code, 204)
		s.refresh_from_db()
		self.assertEqual(s.status, TruckShipment.Status.REGISTERED)
		self.assertTrue(ShipmentStatusEvent.objects.filter(shipment=s).exists())

	def test_transition_stage1_requires_truck_registration(self):
		s = self._create_stage1_shipment(truck_registration='')
		s.packing_list_file = _uploaded('packing.pdf')
		s.invoice_file = _uploaded('invoice.pdf')
		s.importer_tax_clearance_file = _uploaded('tax.pdf')
		s.save()

		url = reverse('shipment_transition', args=[s.id])
		resp = self.client.post(
			url,
			data={'to_status': TruckShipment.Status.REGISTERED},
			**{'HTTP_HX_REQUEST': 'true', 'HTTP_HX_TARGET': 'modal-body'},
		)
		self.assertEqual(resp.status_code, 400)
		s.refresh_from_db()
		self.assertEqual(s.status, TruckShipment.Status.NOT_REGISTERED)

	def test_transition_release_requires_exit_date_and_release_order(self):
		s = self._create_stage1_shipment(status=TruckShipment.Status.RELEASE)
		url = reverse('shipment_transition', args=[s.id])

		# Missing both
		resp = self.client.post(
			url,
			data={'to_status': TruckShipment.Status.COMPLETED},
			**{'HTTP_HX_REQUEST': 'true', 'HTTP_HX_TARGET': 'modal-body'},
		)
		self.assertEqual(resp.status_code, 400)

		# Has date, missing release order
		s.date_exited = timezone.make_aware(datetime(2026, 3, 10, 12, 30))
		s.save()
		resp2 = self.client.post(
			url,
			data={'to_status': TruckShipment.Status.COMPLETED},
			**{'HTTP_HX_REQUEST': 'true', 'HTTP_HX_TARGET': 'modal-body'},
		)
		self.assertEqual(resp2.status_code, 400)

		# Has both
		s.release_order_file = _uploaded('release.pdf')
		s.save()
		resp3 = self.client.post(
			url,
			data={'to_status': TruckShipment.Status.COMPLETED},
			**{'HTTP_HX_REQUEST': 'true', 'HTTP_HX_TARGET': 'modal-body'},
		)
		self.assertEqual(resp3.status_code, 204)
		s.refresh_from_db()
		self.assertEqual(s.status, TruckShipment.Status.COMPLETED)

	def test_filter_by_container_and_document_uploaded(self):
		s1 = self._create_stage1_shipment(container_number='CONT-A')
		s2 = self._create_stage1_shipment(container_number='CONT-B')
		s2.invoice_file = _uploaded('invoice.pdf')
		s2.save()

		url = reverse('shipment_not_registered_list')

		resp = self.client.get(url, {'container_number': 'CONT-A'}, **{'HTTP_HX_REQUEST': 'true'})
		self.assertEqual(resp.status_code, 200)
		page = resp.context['page_obj']
		self.assertEqual(page.paginator.count, 1)
		self.assertEqual(page.object_list[0].id, s1.id)

		resp2 = self.client.get(
			url,
			{'document_type': 'invoice_file', 'document_uploaded': 'uploaded'},
			**{'HTTP_HX_REQUEST': 'true'},
		)
		self.assertEqual(resp2.status_code, 200)
		page2 = resp2.context['page_obj']
		self.assertEqual(page2.paginator.count, 1)
		self.assertEqual(page2.object_list[0].id, s2.id)

	def test_filter_by_duty_range(self):
		self._create_stage1_shipment(container_number='C1', duty_calculation_amount='50.00')
		self._create_stage1_shipment(container_number='C2', duty_calculation_amount='150.00')

		url = reverse('shipment_not_registered_list')
		resp = self.client.get(url, {'duty_min': '100.00'}, **{'HTTP_HX_REQUEST': 'true'})
		self.assertEqual(resp.status_code, 200)
		page = resp.context['page_obj']
		self.assertEqual(page.paginator.count, 1)
		self.assertEqual(page.object_list[0].container_number, 'C2')

	def test_excel_export_contains_new_headers(self):
		self._create_stage1_shipment(container_number='EX-1')
		url = reverse('shipments_export_excel')
		resp = self.client.get(url)
		self.assertEqual(resp.status_code, 200)
		self.assertIn(
			'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
			resp['Content-Type'],
		)

		wb = load_workbook(io.BytesIO(resp.content))
		ws = wb.active
		headers = [cell.value for cell in ws[1]]
		self.assertIn('Container Number', headers)
		self.assertIn('Bill of Lading Number', headers)
		self.assertIn('ETA Date', headers)
		self.assertIn('Duty Calculation Amount (USD)', headers)
		self.assertIn('Release Order', headers)

	def test_completed_zip_export_nests_truck_and_container(self):
		s = self._create_stage1_shipment(
			truck_registration='TRUCK X',
			container_number='CONT/ZIP',
			status=TruckShipment.Status.COMPLETED,
		)
		s.invoice_file = _uploaded('invoice.pdf')
		s.release_order_file = _uploaded('release.pdf')
		s.save()

		url = reverse('shipments_export_documents_zip')
		resp = self.client.get(url)
		self.assertEqual(resp.status_code, 200)
		self.assertEqual(resp['Content-Type'], 'application/zip')

		with zipfile.ZipFile(io.BytesIO(resp.content), 'r') as zf:
			names = set(zf.namelist())

		# safe folder name: spaces and slashes become underscores
		self.assertIn('TRUCK_X/CONT_ZIP/Invoice.pdf', names)
		self.assertIn('TRUCK_X/CONT_ZIP/Release_Order.pdf', names)

	def test_zimra_csv_export_completed_only_and_respects_filters(self):
		completed_a = self._create_stage1_shipment(
			truck_registration='TRUCK A',
			container_number='CONT-A',
			status=TruckShipment.Status.COMPLETED,
		)
		completed_b = self._create_stage1_shipment(
			truck_registration='TRUCK B',
			container_number='CONT-B',
			status=TruckShipment.Status.COMPLETED,
		)
		not_completed = self._create_stage1_shipment(
			truck_registration='TRUCK C',
			container_number='CONT-C',
			status=TruckShipment.Status.NOT_REGISTERED,
		)
		# ensure deterministic ordering isn't relied upon
		self.assertTrue(all([completed_a, completed_b, not_completed]))

		url = reverse('shipments_export_zimra_csv')
		resp = self.client.get(url, {'container_number': 'CONT-A'})
		self.assertEqual(resp.status_code, 200)
		self.assertEqual(resp['Content-Type'], 'text/csv')
		self.assertIn('zimra_export.csv', resp['Content-Disposition'])

		content = resp.content.decode('utf-8')
		rows = list(csv.reader(io.StringIO(content)))
		self.assertGreaterEqual(len(rows), 2)  # header + at least one row
		headers = rows[0]
		self.assertIn('Container Number', headers)

		container_idx = headers.index('Container Number')
		containers = [r[container_idx] for r in rows[1:]]
		self.assertEqual(containers, ['CONT-A'])
