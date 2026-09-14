/* Attach a rich-text editor to the legal document body, if the host project
 * provides one. Soft dependency on purpose: no editor configured (standalone
 * package) means the plain textarea stays, which is a perfectly usable
 * fallback rather than a broken form.
 *
 * The host project supplies window.dkInitQuill (or leaves it undefined)
 * via CONSENT_TRAIL_ADMIN_EDITOR_JS in settings.
 */
document.addEventListener('DOMContentLoaded', function () {
  var ta = document.getElementById('id_body_html');
  if (!ta || typeof window.dkInitQuill !== 'function') return;
  window.dkInitQuill(ta, { uploadUrl: null, noImagesMessage: 'Images are not allowed in legal documents.' });
});
