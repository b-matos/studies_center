// Keeps the "PT"/"EN" navbar link pointing at the equivalent page in the other language,
// instead of always bouncing to that language's home page.
(function () {
  function equivalentPath(path) {
    // A hosting prefix (e.g. /studies_center on GitHub Pages) may come before /pt/ or /en/.
    const match = path.match(/^(.*?)\/(pt|en)\/(.*)$/);
    if (!match) return null;
    const [, prefix, lang, rest] = match;
    const other = lang === "pt" ? "en" : "pt";
    const renamed = rest
      .replace(/^index\.html?$/, "index.html")
      .replace(/^events\.html$/, "events.html")
      .replace(/^queue\.html$/, "queue.html");
    return `${prefix}/${other}/${renamed}`;
  }

  document.addEventListener("DOMContentLoaded", function () {
    const target = equivalentPath(window.location.pathname);
    if (!target) return;
    // Quarto rewrites the navbar's "/en/"/"/pt/" href at build and/or load time into
    // something resolved against the CURRENT profile's own output tree (e.g. ending up
    // as ".../pt/en/" while already inside /pt/), so matching on the href is unreliable.
    // The language toggle is identified by its fixed label text instead.
    document.querySelectorAll(".navbar-nav a.nav-link").forEach((a) => {
      const label = (a.querySelector(".menu-text") || a).textContent.trim();
      if (label === "EN" || label === "PT") {
        a.setAttribute("href", target);
      }
    });
  });
})();
