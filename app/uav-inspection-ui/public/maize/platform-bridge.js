// Report actual WebGL/asset readiness to the platform, rather than iframe load.
// The original offline replay and its metrics remain unchanged.
(() => {
  if (window.parent === window) return
  const loader = document.getElementById('loader')
  if (!loader) return
  const report = (type) => window.parent.postMessage({ type }, window.location.origin)
  const observer = new MutationObserver(() => {
    if (loader.classList.contains('hidden')) {
      observer.disconnect()
      report('maize-inspection:ready')
    } else if (loader.querySelector('strong')?.textContent.includes('未能')) {
      observer.disconnect()
      report('maize-inspection:error')
    }
  })
  observer.observe(loader, { attributes: true, childList: true, characterData: true, subtree: true })
})()
