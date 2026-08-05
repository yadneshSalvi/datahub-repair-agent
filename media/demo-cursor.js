/*
 * Demo capture director, injected via `agent-browser open --init-script`.
 *
 * Why this exists: CDP/Playwright video does not draw the OS pointer, so a scripted
 * recording has no visible sense of agency — the v1 demo looked like a slideshow of
 * static screens. This draws a synthetic cursor and exposes an eased-motion API so
 * every shot can carry continuous, legible movement.
 *
 * Everything here is presentation-only. It never touches app state except by
 * dispatching the same clicks a human would.
 */
(() => {
  if (window.__demo) return

  const CURSOR_ID = '__demo_cursor__'
  const easeInOut = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2)
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))
  const raf = () => new Promise((resolve) => requestAnimationFrame(resolve))

  // Cursor position is tracked in JS rather than read back from the DOM so that a
  // move interrupted mid-flight still starts from where the pointer visually is.
  const state = { x: window.innerWidth * 0.5, y: window.innerHeight * 0.62 }

  function ensureCursor() {
    let node = document.getElementById(CURSOR_ID)
    if (node) return node
    if (!document.body) return null
    node = document.createElement('div')
    node.id = CURSOR_ID
    // Pointer-events none so the synthetic cursor can never eat a click it is
    // standing on top of. z-index above the app's fixed drawers (which use z-50).
    node.style.cssText = [
      'position:fixed', 'left:0', 'top:0', 'width:26px', 'height:26px',
      'pointer-events:none', 'z-index:2147483647',
      'will-change:transform', 'transition:transform 0s',
    ].join(';')
    node.innerHTML =
      '<svg width="26" height="26" viewBox="0 0 26 26" style="filter:drop-shadow(0 2px 5px rgba(0,0,0,.65))">' +
      '<path d="M4 2 L4 19.2 L8.7 14.9 L11.7 21.6 L14.7 20.3 L11.8 13.8 L18.2 13.4 Z" ' +
      'fill="#ffffff" stroke="#0b0d10" stroke-width="1.4" stroke-linejoin="round"/></svg>'
    document.body.appendChild(node)
    apply()
    return node
  }

  function apply() {
    const node = document.getElementById(CURSOR_ID)
    if (node) node.style.transform = `translate3d(${state.x}px, ${state.y}px, 0)`
  }

  function centreOf(target) {
    const el = typeof target === 'string' ? document.querySelector(target) : target
    if (!el) throw new Error(`demo: no element for ${target}`)
    const box = el.getBoundingClientRect()
    return { el, x: box.left + box.width / 2, y: box.top + box.height / 2 }
  }

  /** Glide the pointer along an eased path. Duration is real time, so shots are predictable. */
  async function moveTo(x, y, ms = 700) {
    ensureCursor()
    const from = { x: state.x, y: state.y }
    const start = performance.now()
    for (;;) {
      const t = Math.min(1, (performance.now() - start) / ms)
      const k = easeInOut(t)
      state.x = from.x + (x - from.x) * k
      state.y = from.y + (y - from.y) * k
      apply()
      if (t >= 1) break
      await raf()
    }
  }

  async function moveToEl(target, ms = 700) {
    const { x, y } = centreOf(target)
    await moveTo(x, y, ms)
  }

  /** Brief contraction on click — reads as a press without needing a click sound. */
  async function pulse() {
    const node = ensureCursor()
    if (!node) return
    node.style.transition = 'transform 90ms ease-out'
    node.style.transform = `translate3d(${state.x}px, ${state.y}px, 0) scale(0.78)`
    await sleep(100)
    node.style.transform = `translate3d(${state.x}px, ${state.y}px, 0) scale(1)`
    await sleep(110)
    node.style.transition = 'transform 0s'
  }

  async function click(target, ms = 700) {
    const { el } = centreOf(target)
    await moveToEl(el, ms)
    await pulse()
    el.click()
    await sleep(120)
  }

  /** Eased scroll. An instant jump reads as a hard cut, which is what we are avoiding. */
  async function scrollBy(container, delta, ms = 1200) {
    const node = container ? (typeof container === 'string' ? document.querySelector(container) : container) : null
    const target = node || document.scrollingElement || document.documentElement
    const from = target.scrollTop
    const start = performance.now()
    for (;;) {
      const t = Math.min(1, (performance.now() - start) / ms)
      target.scrollTop = from + delta * easeInOut(t)
      if (t >= 1) break
      await raf()
    }
  }

  async function scrollToEl(target, ms = 1200, offset = 140) {
    const { el } = centreOf(target)
    const box = el.getBoundingClientRect()
    await scrollBy(null, box.top - offset, ms)
  }

  /**
   * CSS `zoom` rather than `transform: scale` — zoom reflows, so glyphs are rasterised
   * at the final size (sharp) and `position: fixed` still resolves correctly. Applied
   * as a step by default; animating it reflows every frame and makes React Flow jitter.
   */
  function zoom(level) {
    document.documentElement.style.zoom = String(level)
  }

  /** Resolves once no skeleton/spinner is in the DOM, so no shot opens on a loading state. */
  async function settled(timeoutMs = 20000) {
    const start = performance.now()
    const isLoading = () =>
      document.querySelector('.animate-pulse, [data-loading="true"], [aria-busy="true"]') !== null
    while (performance.now() - start < timeoutMs) {
      if (!isLoading()) {
        // Two consecutive clean frames — one is not enough while React is committing.
        await raf(); await raf()
        if (!isLoading()) return true
      }
      await sleep(120)
    }
    return false
  }

  function reset() {
    state.x = window.innerWidth * 0.5
    state.y = window.innerHeight * 0.62
    apply()
  }

  // --- shot length ---------------------------------------------------------
  // A clip must always outlast its narration segment. v1 padded short clips by
  // freezing the final frame, which is precisely what produced the 40-second dead
  // stretches. mark()/until() make a shot run long by *continuing to move* instead.

  let markedAt = performance.now()

  function mark() {
    markedAt = performance.now()
  }

  function elapsed() {
    return performance.now() - markedAt
  }

  /**
   * The biggest genuinely scrollable element, largest range first.
   *
   * Most of this app's screens do NOT scroll at the window level — at 1080p the whole page
   * fits and the long content (validation table, evidence drawer, diff pane) lives in inner
   * `overflow:auto` containers. Scrolling `document.scrollingElement` on those pages is a
   * silent no-op, which is why an earlier cut had 16-second stretches where only the pointer
   * moved over a frozen page. Find the real container instead.
   */
  function scrollables() {
    const root = document.scrollingElement || document.documentElement
    const found = []
    if (root.scrollHeight - root.clientHeight > 40) found.push(root)
    for (const el of document.querySelectorAll('div,section,aside,main,ul')) {
      if (el.scrollHeight - el.clientHeight <= 40) continue
      const overflow = getComputedStyle(el).overflowY
      if (overflow === 'auto' || overflow === 'scroll') found.push(el)
    }
    return found.sort((a, b) => (b.scrollHeight - b.clientHeight) - (a.scrollHeight - a.clientHeight))
  }

  /**
   * Keep the shot alive until `totalMs` have passed since mark(), drifting the pointer
   * inside `box` and breathing the scroll position so no frame repeats. Returns early
   * only when the deadline is already behind us.
   */
  async function until(totalMs, box) {
    const area = box || { x: 80, y: 120, w: window.innerWidth - 160, h: window.innerHeight - 240 }
    const targets = scrollables()
    let toggle = 0
    while (elapsed() < totalMs) {
      const remaining = totalMs - elapsed()
      const step = Math.min(950, Math.max(380, remaining))
      await moveTo(area.x + Math.random() * area.w, area.y + Math.random() * area.h, step)
      if (elapsed() >= totalMs) break
      // Oscillate the largest scroller by enough to actually read as movement. Amplitude is
      // capped by the container's own range so a short list never bounces off its end.
      const target = targets[0]
      if (target) {
        const range = target.scrollHeight - target.clientHeight
        const amount = Math.min(150, Math.max(60, Math.floor(range / 3)))
        await scrollBy(target, toggle++ % 2 ? amount : -amount, 620)
      }
    }
  }

  window.__demo = {
    moveTo, moveToEl, click, pulse, scrollBy, scrollToEl, zoom, settled,
    reset, sleep, state, mark, elapsed, until,
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', ensureCursor, { once: true })
  } else {
    ensureCursor()
  }
  // The SPA swaps route subtrees; re-attach if a render ever removes the node.
  setInterval(ensureCursor, 500)
})()
