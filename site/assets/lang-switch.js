// Keeps the "PT"/"EN" navbar link pointing at the equivalent page in the other language,
// instead of always bouncing to that language's home page.
(function () {
  function equivalentPath(path) {
    const match = path.match(/^\/(pt|en)\/(.*)$/);
    if (!match) return null;
    const [, lang, rest] = match;
    const other = lang === "pt" ? "en" : "pt";
    const renamed = rest
      .replace(/^index\.html?$/, "index.html")
      .replace(/^eventos\.html$/, "eventos.html")
      .replace(/^novo\.html$/, "novo.html");
    return `/${other}/${renamed}`;
  }

  document.addEventListener("DOMContentLoaded", function () {
    const target = equivalentPath(window.location.pathname);
    if (!target) return;
    document.querySelectorAll(".navbar-nav a.nav-link").forEach((a) => {
      const href = a.getAttribute("href") || "";
      if (href === "/en/" || href === "/pt/") {
        a.setAttribute("href", target);
      }
    });
  });
})();
