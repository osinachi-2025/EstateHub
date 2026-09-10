// Celtine Properties — shared page interactions (chat switching, filter chips)
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.dash-toggle').forEach(toggle => {
    const dash = toggle.closest('.dash');
    const side = toggle.closest('.dash-side');
    if (!dash || !side) return;
    const storageKey = 'celtine-dashboard-nav-v2';
    const savedPreference = localStorage.getItem(storageKey);
    const collapsed = savedPreference === 'collapsed';
    dash.classList.toggle('nav-collapsed', collapsed);
    side.classList.toggle('is-open', !collapsed);
    toggle.setAttribute('aria-expanded', String(!collapsed));
    toggle.addEventListener('click', () => {
      const nextCollapsed = dash.classList.toggle('nav-collapsed');
      side.classList.toggle('is-open', !nextCollapsed);
      toggle.setAttribute('aria-expanded', String(!nextCollapsed));
      localStorage.setItem(storageKey, nextCollapsed ? 'collapsed' : 'open');
    });
  });

  const mainImage = document.getElementById('propertyMainImage');
  const lightbox = document.getElementById('imageLightbox');
  const lightboxImage = document.getElementById('lightboxImage');
  const closeLightbox = document.getElementById('closeLightbox');
  const openLightbox = image => {
    if (!lightbox || !lightboxImage || !image) return;
    lightboxImage.src = image.src || image.dataset.imageUrl;
    lightboxImage.alt = image.alt || '';
    lightbox.hidden = false;
    lightbox.style.display = 'flex';
    document.body.style.overflow = 'hidden';
  };
  const hideLightbox = () => {
    if (!lightbox) return;
    lightbox.hidden = true;
    lightbox.style.display = 'none';
    document.body.style.overflow = '';
  };
  if (mainImage) mainImage.addEventListener('click', () => openLightbox(mainImage));
  document.querySelectorAll('.property-thumb').forEach(thumb => {
    thumb.addEventListener('click', () => {
      if (!mainImage) return;
      mainImage.src = thumb.dataset.imageUrl;
      mainImage.alt = thumb.querySelector('img')?.alt || mainImage.alt;
      document.querySelectorAll('.property-thumb').forEach(item => {
        item.classList.remove('active');
        item.style.borderColor = 'transparent';
      });
      thumb.classList.add('active');
      thumb.style.borderColor = 'var(--clay)';
      openLightbox(mainImage);
    });
  });
  if (closeLightbox) closeLightbox.addEventListener('click', event => {
    event.stopPropagation();
    hideLightbox();
  });
  if (lightbox) lightbox.addEventListener('click', event => {
    if (event.target === lightbox) hideLightbox();
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') hideLightbox();
  });

  document.querySelectorAll('.chat-list-item').forEach(item => {
    item.addEventListener('click', () => {
      document.querySelectorAll('.chat-list-item').forEach(x => x.classList.remove('on'));
      item.classList.add('on');
      const head = document.querySelector('.chat-head');
      if (head) head.textContent = item.querySelector('.nm').textContent;
    });
  });

  document.querySelectorAll('.chip').forEach(chip => {
    chip.addEventListener('click', (e) => {
      const group = chip.parentElement;
      if (group.classList.contains('plan-feats')) return;
      if (group.children.length > 1) {
        e.preventDefault();
        group.querySelectorAll('.chip').forEach(x => x.classList.remove('on'));
        chip.classList.add('on');
      }
    });
  });
});
