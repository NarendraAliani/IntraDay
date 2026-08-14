// docs/user-guide/js/main.js
//
// Checkpoint 25: vanilla JS driving the Dynamic Digital Tutorial Guide.
// No build step, no framework, no external dependency - must run by
// opening index.html directly from disk (file://), so no fetch() of a
// separate JSON index is used; the search index is built at runtime by
// reading the DOM itself (single source of truth: the HTML content).
(function () {
  "use strict";

  var sections = Array.prototype.slice.call(document.querySelectorAll(".section"));
  var navLinks = Array.prototype.slice.call(document.querySelectorAll(".nav-link"));
  var order = sections.map(function (s) {
    return s.id;
  });

  function sectionTitle(id) {
    var el = document.getElementById(id);
    var h1 = el && el.querySelector("h1, h2");
    return h1 ? h1.textContent.trim() : id;
  }

  function showSection(id, opts) {
    opts = opts || {};
    var found = false;
    sections.forEach(function (section) {
      var active = section.id === id;
      section.classList.toggle("is-active", active);
      if (active) found = true;
    });
    if (!found && sections.length > 0) {
      sections[0].classList.add("is-active");
      id = sections[0].id;
    }
    navLinks.forEach(function (link) {
      link.classList.toggle("is-active", link.getAttribute("data-target") === id);
      link.setAttribute(
        "aria-current",
        link.getAttribute("data-target") === id ? "page" : "false",
      );
    });
    updateProgress(id);
    updatePageNav(id);
    if (!opts.skipScroll) {
      window.scrollTo({ top: 0, behavior: "auto" });
    }
    if (!opts.skipHash) {
      history.replaceState(null, "", "#" + id);
    }
    var mainRegion = document.getElementById("main-content");
    if (mainRegion) mainRegion.focus({ preventScroll: true });
    closeMobileSidebar();
  }

  function updateProgress(id) {
    var idx = order.indexOf(id);
    var fill = document.getElementById("progress-fill");
    var label = document.getElementById("progress-label");
    if (idx === -1 || !fill || !label) return;
    var pct = Math.round(((idx + 1) / order.length) * 100);
    fill.style.width = pct + "%";
    label.textContent = (idx + 1) + " / " + order.length;
  }

  function updatePageNav(id) {
    var idx = order.indexOf(id);
    var prevBtn = document.getElementById("nav-prev");
    var nextBtn = document.getElementById("nav-next");
    if (!prevBtn || !nextBtn) return;
    if (idx <= 0) {
      prevBtn.disabled = true;
      prevBtn.textContent = "← Previous";
    } else {
      prevBtn.disabled = false;
      prevBtn.textContent = "← " + sectionTitle(order[idx - 1]);
    }
    if (idx === -1 || idx >= order.length - 1) {
      nextBtn.disabled = true;
      nextBtn.textContent = "Next →";
    } else {
      nextBtn.disabled = false;
      nextBtn.textContent = sectionTitle(order[idx + 1]) + " →";
    }
  }

  navLinks.forEach(function (link) {
    link.addEventListener("click", function (event) {
      event.preventDefault();
      showSection(link.getAttribute("data-target"));
    });
  });

  document.getElementById("nav-prev").addEventListener("click", function () {
    var current = order.find(function (id) {
      return document.getElementById(id).classList.contains("is-active");
    });
    var idx = order.indexOf(current);
    if (idx > 0) showSection(order[idx - 1]);
  });

  document.getElementById("nav-next").addEventListener("click", function () {
    var current = order.find(function (id) {
      return document.getElementById(id).classList.contains("is-active");
    });
    var idx = order.indexOf(current);
    if (idx < order.length - 1) showSection(order[idx + 1]);
  });

  function closeMobileSidebar() {
    var sidebar = document.getElementById("sidebar");
    if (sidebar) sidebar.classList.remove("is-open");
  }

  var menuToggle = document.getElementById("menu-toggle");
  if (menuToggle) {
    menuToggle.addEventListener("click", function () {
      document.getElementById("sidebar").classList.toggle("is-open");
    });
  }

  // --- Initial section: honor a URL hash (e.g. index.html#dhan-setup),
  // falling back to the first section. Lets other docs deep-link here.
  var initial = (window.location.hash || "").replace("#", "");
  if (!initial || order.indexOf(initial) === -1) {
    initial = order[0];
  }
  showSection(initial, { skipHash: true });

  window.addEventListener("hashchange", function () {
    var id = (window.location.hash || "").replace("#", "");
    if (order.indexOf(id) !== -1) {
      showSection(id, { skipHash: true });
    }
  });

  // --- Client-side search - builds its index from the DOM at runtime,
  // so the guide's own content is the single source of truth (no
  // separate JSON file to keep in sync). No backend, no network call.
  var searchInput = document.getElementById("search-input");
  var searchResults = document.getElementById("search-results");

  function buildIndex() {
    return sections.map(function (section) {
      var text = section.textContent.replace(/\s+/g, " ").trim();
      return {
        id: section.id,
        title: sectionTitle(section.id),
        text: text,
        lowerText: text.toLowerCase(),
      };
    });
  }

  var index = buildIndex();

  function snippet(entry, query) {
    var pos = entry.lowerText.indexOf(query.toLowerCase());
    if (pos === -1) return entry.text.slice(0, 120) + "…";
    var start = Math.max(0, pos - 40);
    var end = Math.min(entry.text.length, pos + query.length + 60);
    return (start > 0 ? "…" : "") + entry.text.slice(start, end) + (end < entry.text.length ? "…" : "");
  }

  function runSearch(query) {
    searchResults.innerHTML = "";
    if (!query || query.trim().length < 2) {
      searchResults.classList.remove("is-open");
      return;
    }
    var q = query.trim().toLowerCase();
    var matches = index.filter(function (entry) {
      return entry.lowerText.indexOf(q) !== -1;
    });
    if (matches.length === 0) {
      var empty = document.createElement("div");
      empty.className = "search-results__empty";
      empty.textContent = 'No results for "' + query + '".';
      searchResults.appendChild(empty);
      searchResults.classList.add("is-open");
      return;
    }
    matches.slice(0, 12).forEach(function (entry) {
      var button = document.createElement("button");
      button.type = "button";
      var strong = document.createElement("strong");
      strong.textContent = entry.title;
      var snip = document.createElement("span");
      snip.textContent = snippet(entry, query);
      button.appendChild(strong);
      button.appendChild(snip);
      button.addEventListener("click", function () {
        showSection(entry.id);
        searchInput.value = "";
        searchResults.classList.remove("is-open");
      });
      searchResults.appendChild(button);
    });
    searchResults.classList.add("is-open");
  }

  if (searchInput) {
    searchInput.addEventListener("input", function () {
      runSearch(searchInput.value);
    });
    searchInput.addEventListener("keydown", function (event) {
      if (event.key === "Escape") {
        searchResults.classList.remove("is-open");
        searchInput.blur();
      }
    });
    document.addEventListener("click", function (event) {
      if (!searchResults.contains(event.target) && event.target !== searchInput) {
        searchResults.classList.remove("is-open");
      }
    });
  }

  // --- First-Day checklist persistence (localStorage - works under
  // file:// in every modern browser; purely cosmetic, never required
  // to use the guide).
  var checklistBoxes = Array.prototype.slice.call(
    document.querySelectorAll('input[type="checkbox"][data-checklist-item]'),
  );
  var STORAGE_KEY = "intraday-user-guide-checklist";

  function loadChecklist() {
    try {
      var raw = window.localStorage.getItem(STORAGE_KEY);
      return raw ? JSON.parse(raw) : {};
    } catch (e) {
      return {};
    }
  }

  function saveChecklist(state) {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
    } catch (e) {
      /* localStorage unavailable (e.g. some restricted local-file
         contexts) - the checklist simply won't persist across
         reloads; the guide remains fully usable either way. */
    }
  }

  var checklistState = loadChecklist();
  checklistBoxes.forEach(function (box) {
    var key = box.getAttribute("data-checklist-item");
    if (checklistState[key]) box.checked = true;
    box.addEventListener("change", function () {
      checklistState[key] = box.checked;
      saveChecklist(checklistState);
    });
  });
})();
