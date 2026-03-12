/* ═══════════════════════════════════════════════════════════════
   Mapping Party Tracker — edit.js
   Project settings + polygon upload management
   ═══════════════════════════════════════════════════════════════ */

MPT.initEditPage = (function ($) {
  'use strict';

  let _projectId;
  let _pendingUploadFile = null;

  return async function initEditPage(projectId) {
    _projectId = projectId;

    const user = await MPT.loadSession();
    MPT.renderHeaderNav(user);

    // Set back link
    $('#back-to-map').attr('href', `/map/${projectId}`);
    $('#edit-project-link').attr('href', `/edit/${projectId}`);

    // Load project settings
    let project;
    try {
      project = await MPT.api.get(`/api/projects/${projectId}`);
    } catch (e) {
      alert('Failed to load project.');
      return;
    }

    // Populate form
    $('#title-input').val(project.title);
    $('#link-url-input').val(project.link_url || '');
    $('#link-text-input').val(project.link_text || '');
    $('#locked-toggle').prop('checked', !!project.locked);

    document.title = `Edit: ${project.title} — Mapping Party Tracker`;

    bindEvents();
  };

  function bindEvents() {
    // Save settings
    $('#save-settings-btn').on('click', saveSettings);

    // Upload drop zone
    MPT.initDropZone(
      $('#upload-drop-zone'),
      $('#upload-input'),
      $('#upload-selected')
    );

    $('#upload-input').on('change', function () {
      _pendingUploadFile = this.files[0] || null;
      // Reset warning
      $('#warning-panel').attr('hidden', '');
      $('#upload-error').attr('hidden', '');
      $('#upload-success').attr('hidden', '');
    });

    $('#upload-btn').on('click', startUpload);
    $('#export-btn').on('click', exportPolygons);
    $('#cancel-upload-btn').on('click', function () {
      $('#warning-panel').attr('hidden', '');
      _pendingUploadFile = null;
      $('#upload-input').val('');
      $('#upload-selected').attr('hidden', '').text('');
    });
    $('#confirm-upload-btn').on('click', function () {
      doUpload(true);
    });
  }

  function exportPolygons() {
    // Trigger download by navigating to the export URL
    window.location.href = `/api/projects/${_projectId}/export`;
  }

  async function saveSettings() {
    const title = $('#title-input').val().trim();
    const linkUrl = $('#link-url-input').val().trim() || null;
    const linkText = $('#link-text-input').val().trim() || null;
    const locked = $('#locked-toggle').is(':checked');

    $('#settings-error').attr('hidden', '');
    $('#settings-success').attr('hidden', '');

    if (!title) {
      showSettingsError('Title is required.');
      return;
    }

    $('#save-settings-btn').prop('disabled', true).text('Saving…');
    try {
      await MPT.api.put(`/api/projects/${_projectId}`, { title, link_url: linkUrl, link_text: linkText, locked });
      $('#settings-success').text('Settings saved!').removeAttr('hidden');
      setTimeout(() => $('#settings-success').attr('hidden', ''), 3000);
    } catch (xhr) {
      const msg = xhr.responseJSON && xhr.responseJSON.detail
        ? xhr.responseJSON.detail : 'Failed to save settings.';
      showSettingsError(msg);
    } finally {
      $('#save-settings-btn').prop('disabled', false).text('Save Settings');
    }
  }

  function showSettingsError(msg) {
    $('#settings-error').text(msg).removeAttr('hidden');
  }

  function startUpload() {
    const file = document.getElementById('upload-input').files[0];
    if (!file) {
      $('#upload-error').text('Please select a GeoJSON file.').removeAttr('hidden');
      return;
    }
    _pendingUploadFile = file;
    doUpload(false);
  }

  async function doUpload(confirmed) {
    if (!_pendingUploadFile) return;

    $('#upload-error').attr('hidden', '');
    $('#upload-success').attr('hidden', '');
    $('#upload-btn').prop('disabled', true).text('Uploading…');
    $('#confirm-upload-btn').prop('disabled', true);

    const formData = new FormData();
    formData.append('geojson_file', _pendingUploadFile);
    formData.append('confirm', confirmed ? 'true' : 'false');

    try {
      const res = await MPT.api.postForm(`/api/projects/${_projectId}/upload`, formData);

      if (res.needs_confirm) {
        // Show warning panel
        const $list = $('#warning-list').empty();
        (res.warnings || []).forEach(w => $list.append(`<li>${MPT.escHtml(w)}</li>`));
        $('#warning-panel').removeAttr('hidden');
        $('#confirm-upload-btn').prop('disabled', false);
      } else {
        $('#warning-panel').attr('hidden', '');
        _pendingUploadFile = null;
        $('#upload-input').val('');
        $('#upload-selected').attr('hidden', '').text('');
        const msg = `Done — ${res.added} added, ${res.kept} kept, ${res.removed} removed.`;
        $('#upload-success').text(msg).removeAttr('hidden');
        setTimeout(() => $('#upload-success').attr('hidden', ''), 5000);
      }
    } catch (xhr) {
      const msg = xhr.responseJSON && xhr.responseJSON.detail
        ? xhr.responseJSON.detail : 'Upload failed.';
      $('#upload-error').text(msg).removeAttr('hidden');
    } finally {
      $('#upload-btn').prop('disabled', false).text('Upload GeoJSON');
    }
  }

})(jQuery);
