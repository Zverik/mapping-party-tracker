/* ═══════════════════════════════════════════════════════════════
   Mapping Party Tracker — main.js
   Shared utilities and homepage initializer
   ═══════════════════════════════════════════════════════════════ */

const MPT = (function ($) {
  'use strict';

  // ─── API helpers ──────────────────────────────────────────────────

  const api = {
    get(url) {
      return $.ajax({ url, method: 'GET' });
    },
    post(url, data) {
      return $.ajax({
        url,
        method: 'POST',
        contentType: 'application/json',
        data: JSON.stringify(data),
      });
    },
    put(url, data) {
      return $.ajax({
        url,
        method: 'PUT',
        contentType: 'application/json',
        data: JSON.stringify(data),
      });
    },
    postForm(url, formData) {
      return $.ajax({
        url,
        method: 'POST',
        data: formData,
        processData: false,
        contentType: false,
      });
    },
  };

  // ─── Session/auth ──────────────────────────────────────────────────

  let _currentUser = null;

  async function loadSession() {
    try {
      const data = await api.get('/api/me');
      _currentUser = data.authenticated ? data : null;
    } catch (e) {
      _currentUser = null;
    }
    return _currentUser;
  }

  function getCurrentUser() { return _currentUser; }

  function renderHeaderNav(user) {
    const $nav = $('#header-nav');
    if (user && user.authenticated) {
      $nav.html(`
        <span class="nav-username">@${escHtml(user.username)}</span>
        <form method="POST" action="/auth/logout" style="margin:0">
          <button type="submit" class="btn btn-logout">Logout</button>
        </form>
      `);
    } else {
      $nav.html(`<a href="/auth/login" class="btn btn-login">Login with OSM</a>`);
    }
  }

  // ─── Escape HTML ──────────────────────────────────────────────────

  function escHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  // ─── File drop zone ────────────────────────────────────────────────

  function initDropZone($zone, $input, $selectedLabel) {
    $input.on('click', (e) => e.stopPropagation());
    $zone.on('click', () => $input.trigger('click'));

    $zone.on('dragover dragenter', (e) => {
      e.preventDefault();
      $zone.addClass('drag-over');
    });
    $zone.on('dragleave drop', (e) => {
      e.preventDefault();
      $zone.removeClass('drag-over');
    });
    $zone.on('drop', (e) => {
      const file = e.originalEvent.dataTransfer.files[0];
      if (file) { setFile($input[0], file, $selectedLabel); }
    });
    $input.on('change', function () {
      if (this.files[0]) { setFile(this, this.files[0], $selectedLabel); }
    });
  }

  function setFile(inputEl, file, $label) {
    // Create new FileList-like via DataTransfer
    try {
      const dt = new DataTransfer();
      dt.items.add(file);
      inputEl.files = dt.files;
    } catch (e) { /* ignore – some browsers */ }
    $label.text('📄 ' + file.name).removeAttr('hidden');
  }

  // ─── Homepage ──────────────────────────────────────────────────────

  async function initHomePage() {
    const user = await loadSession();
    renderHeaderNav(user);

    if (user && user.authenticated) {
      $('#new-project-btn').show();
    }

    loadProjects();
    bindHomeEvents();
  }

  function loadProjects() {
    api.get('/api/projects').then(function (projects) {
      const $list = $('#projects-list');
      if (!projects.length) {
        $list.html('<div class="empty-state">No projects yet. Create one to get started!</div>');
        return;
      }
      $list.empty();
      projects.forEach(function (p) {
        const lockedBadge = p.locked
          ? '<span class="project-card-badge badge-locked">LOCKED</span>' : '';
        const card = `
          <div class="project-card" data-id="${p.id}">
            ${lockedBadge}
            <div class="project-card-title">${escHtml(p.title)}</div>
            <div class="project-card-meta">
              <div class="meta-item">
                <span class="meta-value">${p.total_polygons || 0}</span>
                <span class="meta-label">Polygons</span>
              </div>
              <div class="meta-item">
                <span class="meta-value">${p.claimed_polygons || 0}</span>
                <span class="meta-label">Claimed</span>
              </div>
              <div class="meta-item">
                <span class="meta-value">${Math.max(0, (p.total_polygons || 0) - (p.claimed_polygons || 0))}</span>
                <span class="meta-label">Free</span>
              </div>
            </div>
          </div>`;
        $list.append(card);
      });
    }).fail(function () {
      $('#projects-list').html('<div class="empty-state">Failed to load projects.</div>');
    });
  }

  function bindHomeEvents() {
    $('#new-project-btn').on('click', () => {
      $('#new-project-modal').removeAttr('hidden');
      $('#project-title').focus();
    });

    $('#modal-close, #cancel-btn').on('click', closeModal);
    $('#new-project-modal').on('click', function (e) {
      if ($(e.target).is('#new-project-modal')) { closeModal(); }
    });

    initDropZone(
      $('#file-drop-zone'),
      $('#geojson-input'),
      $('#file-selected')
    );

    $(document).on('keydown', function (e) {
      if (e.key === 'Escape') { closeModal(); }
    });

    $('#create-btn').on('click', createProject);

    $(document).on('click', '.project-card', function () {
      const id = $(this).data('id');
      window.location.href = `/map/${id}`;
    });
  }

  function closeModal() {
    $('#new-project-modal').attr('hidden', '');
    $('#create-error').attr('hidden', '').text('');
    $('#project-title').val('');
    $('#geojson-input').val('');
    $('#file-selected').attr('hidden', '').text('');
  }

  function createProject() {
    const title = $('#project-title').val().trim();
    const fileInput = document.getElementById('geojson-input');
    const file = fileInput && fileInput.files[0];

    $('#create-error').attr('hidden', '').text('');

    if (!title) {
      showCreateError('Please enter a project title.');
      return;
    }
    if (!file) {
      showCreateError('Please select a GeoJSON file.');
      return;
    }

    const formData = new FormData();
    formData.append('title', title);
    formData.append('geojson_file', file);

    $('#create-btn').prop('disabled', true).text('Creating…');

    api.postForm('/api/projects', formData)
      .then(function (res) {
        window.location.href = `/map/${res.id}`;
      })
      .fail(function (xhr) {
        const msg = xhr.responseJSON && xhr.responseJSON.detail
          ? xhr.responseJSON.detail
          : 'Failed to create project.';
        showCreateError(msg);
        $('#create-btn').prop('disabled', false).text('Create Project');
      });
  }

  function showCreateError(msg) {
    $('#create-error').text(msg).removeAttr('hidden');
  }

  // ─── Public API ────────────────────────────────────────────────────

  return {
    api,
    loadSession,
    getCurrentUser,
    renderHeaderNav,
    escHtml,
    initDropZone,
    initHomePage,
  };

})(jQuery);
