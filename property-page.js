function propertyPage() {
  const propertyImages = Array.isArray(window.propertyImages) ? window.propertyImages : [];

  return {
    propertyImages,
    modalOpen: false,
    currentSlide: 0,
    _touchStartX: null,
    _touchStartY: null,
    _touchDeltaX: 0,
    _touchDeltaY: 0,
    init() {
      // Lock page scroll only while the modal is open.
      this.$watch('modalOpen', (open) => {
        document.body.style.overflow = open ? 'hidden' : '';
      });
    },
    openModal(index) {
      this.currentSlide = typeof index === 'number' ? index : 0;
      this.modalOpen = true;
    },
    closeModal() {
      this.modalOpen = false;
    },
    next() {
      if (!this.propertyImages.length) return;
      this.currentSlide = (this.currentSlide + 1) % this.propertyImages.length;
    },
    prev() {
      if (!this.propertyImages.length) return;
      this.currentSlide = (this.currentSlide - 1 + this.propertyImages.length) % this.propertyImages.length;
    },
    onTouchStart(e) {
      const t = e.touches?.[0];
      if (!t) return;
      this._touchStartX = t.clientX;
      this._touchStartY = t.clientY;
      this._touchDeltaX = 0;
      this._touchDeltaY = 0;
    },
    onTouchMove(e) {
      const t = e.touches?.[0];
      if (!t || this._touchStartX === null || this._touchStartY === null) return;
      this._touchDeltaX = t.clientX - this._touchStartX;
      this._touchDeltaY = t.clientY - this._touchStartY;
    },
    onTouchEnd() {
      const threshold = 45;
      const isHorizontal = Math.abs(this._touchDeltaX) > Math.abs(this._touchDeltaY);

      if (isHorizontal && Math.abs(this._touchDeltaX) >= threshold) {
        if (this._touchDeltaX < 0) this.next();
        else this.prev();
      }

      this._touchStartX = null;
      this._touchStartY = null;
      this._touchDeltaX = 0;
      this._touchDeltaY = 0;
    },
  };
}

