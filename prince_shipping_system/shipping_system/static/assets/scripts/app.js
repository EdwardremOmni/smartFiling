(function () {
  function getModal() {
    var modalEl = document.getElementById('appModal');
    if (!modalEl || !window.bootstrap) return null;
    return bootstrap.Modal.getOrCreateInstance(modalEl, { backdrop: 'static' });
  }

  function closeModal() {
    var modal = getModal();
    if (!modal) return;
    modal.hide();
  }

  function clearModalBody() {
    var body = document.getElementById('modal-body');
    if (body) body.innerHTML = '';
  }

  function getQueryFor(targetId) {
    var input = document.querySelector('input[name="q"][hx-target="#' + targetId + '"]');
    return input ? (input.value || '') : '';
  }

  function getPerPageFor(targetId) {
    var select = document.querySelector('select[name="per_page"][hx-target="#' + targetId + '"]');
    return select ? (select.value || '') : '';
  }

  function getPageFromUrl() {
    try {
      var sp = new URLSearchParams(window.location.search || '');
      return sp.get('page') || '';
    } catch (e) {
      return '';
    }
  }

  function refreshTableIfPresent(targetId, urlBase) {
    var el = document.getElementById(targetId);
    if (!el || !window.htmx) return;
    var q = getQueryFor(targetId);
    var perPage = getPerPageFor(targetId);
    var page = getPageFromUrl();

    var params = new URLSearchParams();
    if (q) params.set('q', q);
    if (perPage) params.set('per_page', perPage);
    if (page) params.set('page', page);

    var qs = params.toString();
    var url = qs ? (urlBase + '?' + qs) : urlBase;
    htmx.ajax('GET', url, { target: '#' + targetId, swap: 'innerHTML' });
  }

  function setActiveNav() {
    var path = window.location.pathname || '';
    document.querySelectorAll('.app-nav a').forEach(function (a) {
      var href = a.getAttribute('href') || '';
      try {
        var url = new URL(href, window.location.origin);
        var isActive = url.pathname === path;
        a.classList.toggle('is-active', isActive);
      } catch (e) {
        // ignore
      }
    });
  }

  document.addEventListener('DOMContentLoaded', setActiveNav);
  document.addEventListener('htmx:pushedIntoHistory', setActiveNav);
  window.addEventListener('popstate', setActiveNav);

  // Open modal when HTMX swaps into modal-body
  document.addEventListener('htmx:afterSwap', function (evt) {
    if (!evt || !evt.detail || !evt.detail.target) return;
    if (evt.detail.target.id === 'modal-body') {
      var modal = getModal();
      if (modal) modal.show();

      // If the swapped-in modal content marks a field with autofocus,
      // focus it after Bootstrap finishes rendering.
      window.setTimeout(function () {
        try {
          var body = document.getElementById('modal-body');
          if (!body) return;
          var el = body.querySelector('[autofocus]');
          if (el && typeof el.focus === 'function') el.focus();
          if (el && typeof el.select === 'function') el.select();
        } catch (e) {
          // ignore
        }
      }, 50);
    }
  });

  // Clear modal body after close
  document.addEventListener('hidden.bs.modal', function (evt) {
    if (evt && evt.target && evt.target.id === 'appModal') {
      clearModalBody();
    }
  });

  // Custom trigger events from the server
  document.body.addEventListener('closeModal', function () {
    closeModal();
  });

  document.body.addEventListener('importersChanged', function () {
    refreshTableIfPresent('importer-table', '/importers/');
  });
  document.body.addEventListener('usersChanged', function () {
    refreshTableIfPresent('user-table', '/users/');
  });
  document.body.addEventListener('billsChanged', function () {
    refreshTableIfPresent('bill-table', '/bills_of_entry/');
  });
  document.body.addEventListener('docsChanged', function () {
    refreshTableIfPresent('doc-table', '/internal_documents/');
  });

  document.body.addEventListener('agreementsChanged', function () {
    refreshTableIfPresent('agreement-table', '/agreements/');
  });

  document.addEventListener('htmx:afterSwap', function (evt) {
    // subtle motion for swapped-in content
    if (evt && evt.detail && evt.detail.target && evt.detail.target.id === 'main-content') {
      evt.detail.target.classList.remove('app-fade-enter');
      // trigger reflow
      void evt.detail.target.offsetWidth;
      evt.detail.target.classList.add('app-fade-enter');
    }
  });
})();
