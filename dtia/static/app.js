"use strict";

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

const app = {
  state: null,
  items: [],
  total: 0,
  offset: 0,
  limit: 60,
  loading: false,
  view: "all",
  rootId: "",
  collectionId: "",
  query: "",
  orientation: "",
  format: "",
  rating: "",
  minWidth: "",
  tag: "",
  sort: "newest",
  detail: null,
  managedRoot: null,
  revealed: new Set(),
  trackedJob: null,
  searchTimer: null,
};

function icon(name) {
  return `<svg aria-hidden="true"><use href="#i-${name}"/></svg>`;
}

function escapeHTML(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

async function api(path, options = {}) {
  const init = { ...options, headers: { ...(options.headers || {}) } };
  if (options.body && typeof options.body !== "string") {
    init.body = JSON.stringify(options.body);
    init.headers["Content-Type"] = "application/json";
  }
  const response = await fetch(path, init);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || "A operação não pôde ser concluída.");
  return payload;
}

function toast(message, kind = "success") {
  const node = document.createElement("div");
  node.className = `toast ${kind}`;
  node.textContent = message;
  $("#toastStack").append(node);
  setTimeout(() => node.remove(), 4300);
}

function plural(value, one, many = `${one}s`) {
  return `${Number(value).toLocaleString("pt-BR")} ${value === 1 ? one : many}`;
}

function bytesLabel(bytes) {
  const value = Number(bytes || 0);
  if (value < 1024) return `${value} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let current = value / 1024;
  let index = 0;
  while (current >= 1024 && index < units.length - 1) {
    current /= 1024;
    index += 1;
  }
  return `${current >= 10 ? current.toFixed(1) : current.toFixed(2)} ${units[index]}`;
}

function privacyMode(item) {
  if (!app.state) return "show";
  if (item.rating === "adult") return app.state.settings.adult_visibility || "blur";
  if (item.rating === "sensitive") return app.state.settings.sensitive_visibility || "show";
  return "show";
}

function privateLabel(item) {
  return item.rating === "adult" ? "Conteúdo adulto / NSFW" : "Conteúdo sensível";
}

function viewCopy() {
  if (app.rootId) {
    const root = app.state?.roots.find((item) => String(item.id) === String(app.rootId));
    return {
      eyebrow: root?.available ? "FONTE CONECTADA" : "FONTE DESCONECTADA",
      title: root?.label || "Pasta local",
      description: root?.available
        ? "Arquivos catalogados diretamente desta pasta ou unidade."
        : "O índice permanece disponível; conecte novamente a unidade para abrir os originais.",
    };
  }
  if (app.collectionId) {
    const collection = app.state?.collections.find((item) => String(item.id) === String(app.collectionId));
    return {
      eyebrow: "COLEÇÃO VIRTUAL",
      title: collection?.name || "Coleção",
      description: collection?.description || "Imagens agrupadas sem alterar suas pastas originais.",
    };
  }
  const copies = {
    all: ["ARQUIVO LOCAL", "Todo o acervo", "Imagens catalogadas diretamente dos seus discos, sem duplicar os arquivos originais."],
    favorites: ["SELEÇÃO", "Favoritos", "As imagens marcadas para acesso rápido."],
    duplicates: ["VERIFICAÇÃO", "Duplicatas exatas", "Arquivos com conteúdo idêntico, mesmo quando os nomes ou as pastas são diferentes."],
    offline: ["DISPONIBILIDADE", "Arquivos indisponíveis", "Itens de unidades desconectadas, arquivos removidos ou formatos que não puderam ser lidos."],
  };
  const current = copies[app.view] || copies.all;
  return { eyebrow: current[0], title: current[1], description: current[2] };
}

async function refreshState() {
  app.state = await api("/api/state");
  renderState();
  const running = app.state.jobs.find((job) => ["queued", "running"].includes(job.status));
  if (running && app.trackedJob !== running.id) trackJob(running.id);
}

function renderState() {
  const { counts, roots, collections, tags, settings, version } = app.state;
  $("#totalCount").textContent = counts.total.toLocaleString("pt-BR");
  $("#favoriteCount").textContent = counts.favorites.toLocaleString("pt-BR");
  $("#duplicateCount").textContent = counts.duplicate_files.toLocaleString("pt-BR");
  $("#offlineCount").textContent = counts.unavailable.toLocaleString("pt-BR");
  $("#versionLabel").textContent = `v${version} • índice privado`;

  $("#rootList").innerHTML = roots.length
    ? roots.map((root) => `
      <div class="source-row">
        <button data-root="${root.id}" class="source-main ${String(app.rootId) === String(root.id) ? "active" : ""}" title="${escapeHTML(root.path)}">
          <span class="source-dot ${root.available ? "online" : "offline"}"></span>
          <span>${escapeHTML(root.label)}</span>
          <small>${Number(root.image_count || 0).toLocaleString("pt-BR")}</small>
        </button>
        <button class="source-manage" data-manage-root="${root.id}" title="Gerenciar ${escapeHTML(root.label)}" aria-label="Gerenciar ${escapeHTML(root.label)}">${icon("more")}</button>
      </div>`).join("")
    : `<span class="muted">Nenhuma fonte adicionada</span>`;

  $("#collectionList").innerHTML = collections.length
    ? collections.map((collection) => `
      <button data-collection="${collection.id}" class="${String(app.collectionId) === String(collection.id) ? "active" : ""}">
        <span class="collection-dot"></span>
        <span>${escapeHTML(collection.name)}</span>
        <small>${Number(collection.image_count || 0).toLocaleString("pt-BR")}</small>
      </button>`).join("")
    : `<span class="muted">Nenhuma coleção ainda</span>`;

  $("#tagCloud").innerHTML = tags.length
    ? tags.slice(0, 18).map((tag) => `<button data-tag="${escapeHTML(tag.name)}" class="${app.tag === tag.name ? "active" : ""}">#${escapeHTML(tag.name)} <small>${tag.count}</small></button>`).join("")
    : `<span class="muted">Nenhuma tag ainda</span>`;

  $("#adultVisibility").value = settings.adult_visibility || "blur";
  $("#sensitiveVisibility").value = settings.sensitive_visibility || "show";
  const privacyText = settings.adult_visibility === "hide" ? "oculto" : settings.adult_visibility === "show" ? "visível" : "desfocado";
  $("#privacyButton").title = `Conteúdo adulto: ${privacyText}`;
  updateActiveNavigation();
}

function updateActiveNavigation() {
  $$(".nav-item").forEach((button) => button.classList.toggle("active", !app.rootId && !app.collectionId && button.dataset.view === app.view));
  $$("[data-root]").forEach((button) => button.classList.toggle("active", String(button.dataset.root) === String(app.rootId)));
  $$("[data-collection]").forEach((button) => button.classList.toggle("active", String(button.dataset.collection) === String(app.collectionId)));
  const copy = viewCopy();
  $("#eyebrow").textContent = copy.eyebrow;
  $("#viewTitle").textContent = copy.title;
  $("#viewDescription").textContent = copy.description;
}

function queryParameters() {
  const values = {
    q: app.query,
    orientation: app.orientation,
    format: app.format,
    rating: app.rating,
    min_width: app.minWidth,
    tag: app.tag,
    sort: app.sort,
    limit: app.limit,
    offset: app.offset,
  };
  if (app.rootId) values.root_id = app.rootId;
  if (app.collectionId) values.collection_id = app.collectionId;
  if (app.view === "favorites") values.favorite = "1";
  if (["duplicates", "offline"].includes(app.view)) values.view = app.view;
  const parameters = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => {
    if (value !== "" && value !== null && value !== undefined) parameters.set(key, value);
  });
  return parameters;
}

async function loadImages(reset = true) {
  if (app.loading) return;
  app.loading = true;
  if (reset) {
    app.offset = 0;
    app.items = [];
    $("#gallery").innerHTML = "";
  }
  try {
    const result = await api(`/api/images?${queryParameters()}`);
    app.total = result.total;
    app.items.push(...result.items);
    app.offset = app.items.length;
    renderGallery();
  } catch (error) {
    toast(error.message, "warning");
  } finally {
    app.loading = false;
  }
}

function renderGallery() {
  const hasNoArchive = app.state.roots.length === 0 && app.state.counts.total === 0;
  $("#resultCount").textContent = plural(app.total, "imagem", "imagens");
  $("#emptyState").classList.toggle("hidden", !hasNoArchive);
  $("#gallery").classList.toggle("hidden", hasNoArchive);

  if (!hasNoArchive && app.items.length === 0) {
    $("#gallery").innerHTML = `
      <div class="empty-state">
        <span class="empty-mark">${icon("search")}</span>
        <p class="eyebrow">NENHUM RESULTADO</p>
        <h2>Nada encontrado neste recorte</h2>
        <p>Tente limpar os filtros, usar outro termo ou reconectar a unidade onde os arquivos estão salvos.</p>
        <button class="button ghost" data-action="clear-filters">Limpar filtros</button>
      </div>`;
  } else if (!hasNoArchive) {
    $("#gallery").innerHTML = app.items.map(imageCard).join("");
  }
  const canLoad = app.items.length < app.total && app.sort !== "random";
  $("#loadMore").classList.toggle("hidden", !canLoad);
  updateActiveNavigation();
}

function imageCard(item, index) {
  const mode = privacyMode(item);
  const isPrivate = mode === "blur" && !app.revealed.has(item.id);
  const available = item.status === "online" && item.root_available;
  const title = item.title || item.filename;
  const dimensions = item.width && item.height ? `${item.width}×${item.height}` : "sem leitura";
  const status = !available ? `<span class="card-status">${item.status === "error" ? "ERRO" : "OFFLINE"}</span>` : "";
  const media = item.thumbnail_url && item.status !== "error"
    ? `<img src="${item.thumbnail_url}" alt="" loading="lazy" decoding="async">`
    : icon("offline");
  const cover = isPrivate ? `
    <span class="private-cover" data-action="reveal" data-id="${item.id}">
      ${icon("eye-off")}<strong>${escapeHTML(privateLabel(item))}</strong><span>Clique para revelar nesta sessão</span>
    </span>` : "";
  return `
    <article class="image-card ${isPrivate ? "private" : ""} ${app.revealed.has(item.id) ? "revealed" : ""} ${item.status === "error" ? "error" : ""}" data-id="${item.id}">
      <button class="card-media" data-action="details" data-id="${item.id}" aria-label="Abrir ${escapeHTML(title)}">
        ${media}
        <span class="card-shade"></span>
        <span class="card-index">${String(index + 1).padStart(3, "0")}</span>
        ${status}
        <span class="card-data"><strong>${escapeHTML(title)}</strong><small>${escapeHTML(dimensions)} • ${escapeHTML(item.extension.toUpperCase())} • ${escapeHTML(bytesLabel(item.byte_size))}</small></span>
        ${cover}
      </button>
      <button class="card-favorite ${item.favorite ? "active" : ""}" data-action="favorite" data-id="${item.id}" aria-label="${item.favorite ? "Remover dos favoritos" : "Adicionar aos favoritos"}">${icon("heart")}</button>
    </article>`;
}

function selectView(view, rootId = "", collectionId = "") {
  app.view = view;
  app.rootId = rootId;
  app.collectionId = collectionId;
  closeMobilePanels();
  updateActiveNavigation();
  loadImages(true);
}

function clearFilters() {
  app.query = "";
  app.orientation = "";
  app.format = "";
  app.rating = "";
  app.minWidth = "";
  app.tag = "";
  $("#searchInput").value = "";
  $("#formatFilter").value = "";
  $("#ratingFilter").value = "";
  $("#widthFilter").value = "";
  $$("#orientationFilter button").forEach((button) => button.classList.toggle("active", button.dataset.value === ""));
  if (app.state) renderState();
  loadImages(true);
}

async function setFavorite(imageId) {
  const item = app.items.find((candidate) => candidate.id === imageId);
  if (!item) return;
  const next = !item.favorite;
  item.favorite = next;
  renderGallery();
  try {
    await api(`/api/images/${imageId}`, { method: "PATCH", body: { favorite: next } });
    await refreshState();
    if (app.view === "favorites" && !next) loadImages(true);
  } catch (error) {
    item.favorite = !next;
    renderGallery();
    toast(error.message, "warning");
  }
}

async function openDetails(imageId) {
  try {
    app.detail = await api(`/api/images/${imageId}`);
    renderDetails();
    $("#detailDialog").showModal();
  } catch (error) {
    toast(error.message, "warning");
  }
}

function renderDetails() {
  const item = app.detail;
  const mode = privacyMode(item);
  const isPrivate = mode === "blur" && !app.revealed.has(item.id);
  $("#detailTitle").value = item.title || item.filename;
  $("#detailPath").textContent = item.path;
  $("#detailRating").value = item.rating;
  $("#detailTags").value = (item.tags || []).join(", ");
  $("#detailNotes").value = item.notes || "";
  $("#openOriginal").href = item.original_url;
  $("#detailFavorite").classList.toggle("active", item.favorite);
  $("#detailFavorite span").textContent = item.favorite ? "Favoritado" : "Favoritar";

  $("#detailMedia").className = `detail-media ${isPrivate ? "private" : ""}`;
  $("#detailMedia").innerHTML = `
    <img src="${item.original_url}" alt="${escapeHTML(item.title || item.filename)}">
    ${isPrivate ? `<button class="detail-reveal" data-action="reveal-detail">${icon("eye-off")}<strong>${escapeHTML(privateLabel(item))}</strong><span>O arquivo está apenas desfocado na interface. Clique para revelar nesta sessão.</span></button>` : ""}`;

  const metadata = [
    ["Dimensões", item.width && item.height ? `${item.width} × ${item.height} px` : "Não disponível"],
    ["Formato", String(item.extension || "—").toUpperCase()],
    ["Tamanho", bytesLabel(item.byte_size)],
    ["Fonte", item.root_label || "Pasta desconectada"],
    ["Câmera", item.camera || "Não informada"],
    ["Data da captura", item.date_taken || "Não informada"],
  ];
  $("#metadataGrid").innerHTML = metadata.map(([label, value]) => `<div><span>${escapeHTML(label)}</span><strong title="${escapeHTML(value)}">${escapeHTML(value)}</strong></div>`).join("");

  $("#detailCollections").innerHTML = app.state.collections.length
    ? app.state.collections.map((collection) => `<label class="collection-check"><input type="checkbox" value="${collection.id}" ${item.collection_ids.includes(collection.id) ? "checked" : ""}><span>${escapeHTML(collection.name)}</span></label>`).join("")
    : `<span class="muted">Crie uma coleção pelo botão + na barra lateral.</span>`;

  const exif = Object.entries(item.exif || {});
  $("#exifList").innerHTML = exif.length
    ? exif.map(([key, value]) => `<dt>${escapeHTML(key)}</dt><dd>${escapeHTML(value)}</dd>`).join("")
    : `<dt>EXIF</dt><dd>Nenhum metadado incorporado foi encontrado.</dd>`;

  const duplicates = item.duplicates || [];
  $("#duplicateNotice").classList.toggle("hidden", duplicates.length === 0);
  $("#duplicateNotice").innerHTML = duplicates.length
    ? `<strong>${plural(duplicates.length, "cópia idêntica", "cópias idênticas")} detectada${duplicates.length === 1 ? "" : "s"}.</strong><br>${duplicates.map((copy) => escapeHTML(copy.path)).join("<br>")}`
    : "";
}

async function saveDetails() {
  if (!app.detail) return;
  const button = $("#saveDetails");
  button.disabled = true;
  const tags = $("#detailTags").value.split(",").map((value) => value.trim()).filter(Boolean);
  const collectionIds = $$("#detailCollections input:checked").map((input) => Number(input.value));
  try {
    app.detail = await api(`/api/images/${app.detail.id}`, {
      method: "PATCH",
      body: {
        title: $("#detailTitle").value,
        rating: $("#detailRating").value,
        tags,
        notes: $("#detailNotes").value,
        collection_ids: collectionIds,
      },
    });
    toast("Metadados salvos no índice local.");
    await refreshState();
    await loadImages(true);
    if (privacyMode(app.detail) === "hide") {
      $("#detailDialog").close();
      toast("A imagem foi ocultada conforme sua preferência de privacidade.", "warning");
    } else {
      renderDetails();
    }
  } catch (error) {
    toast(error.message, "warning");
  } finally {
    button.disabled = false;
  }
}

async function toggleDetailFavorite() {
  if (!app.detail) return;
  const next = !app.detail.favorite;
  try {
    app.detail = await api(`/api/images/${app.detail.id}`, { method: "PATCH", body: { favorite: next } });
    renderDetails();
    await refreshState();
    await loadImages(true);
  } catch (error) {
    toast(error.message, "warning");
  }
}

async function addFolder() {
  const buttons = [$("#addFolderButton"), $("#addFolderMini"), $("#emptyAddFolder")];
  buttons.forEach((button) => { button.disabled = true; });
  toast("Aguardando a escolha da pasta…", "warning");
  try {
    const result = await api("/api/roots/pick", { method: "POST", body: {} });
    if (result.cancelled) return;
    toast(`Pasta “${result.root.label}” adicionada. A indexação começou.`);
    await refreshState();
    selectView("all", result.root.id, "");
    trackJob(result.job.id);
  } catch (error) {
    toast(`${error.message} Você também pode informar o caminho manualmente.`, "warning");
    $("#pathDialog").showModal();
  } finally {
    buttons.forEach((button) => { button.disabled = false; });
  }
}

async function addManualPath(event) {
  event.preventDefault();
  const submit = $("#pathForm button[type=submit]");
  submit.disabled = true;
  try {
    const result = await api("/api/roots", {
      method: "POST",
      body: { path: $("#manualPath").value, label: $("#manualLabel").value },
    });
    $("#pathDialog").close();
    $("#pathForm").reset();
    toast(`Pasta “${result.root.label}” adicionada. A indexação começou.`);
    await refreshState();
    selectView("all", result.root.id, "");
    trackJob(result.job.id);
  } catch (error) {
    toast(error.message, "warning");
  } finally {
    submit.disabled = false;
  }
}

async function scanAll() {
  try {
    const job = await api("/api/scan", { method: "POST", body: {} });
    toast("Reindexação iniciada.");
    trackJob(job.id);
  } catch (error) {
    toast(error.message, "warning");
  }
}

async function trackJob(jobId) {
  if (!jobId) return;
  app.trackedJob = jobId;
  const panel = $("#scanPanel");
  panel.classList.remove("hidden");
  const poll = async () => {
    if (app.trackedJob !== jobId) return;
    try {
      const job = await api(`/api/jobs/${jobId}`);
      $("#scanTitle").textContent = job.message || "Indexando…";
      $("#scanCurrent").textContent = job.current || `${job.root_index || 0} de ${job.root_count || 0} fontes`;
      $("#scanNumbers").textContent = `${Number(job.indexed || 0).toLocaleString("pt-BR")} novas • ${Number(job.unchanged || 0).toLocaleString("pt-BR")} inalteradas • ${Number(job.errors || 0).toLocaleString("pt-BR")} erros`;
      const rolling = 18 + ((Number(job.processed || 0) * 3) % 72);
      $("#scanProgress").style.width = `${job.status === "completed" ? 100 : rolling}%`;
      if (["queued", "running"].includes(job.status)) {
        setTimeout(poll, 700);
      } else {
        app.trackedJob = null;
        await refreshState();
        await loadImages(true);
        toast(job.status === "completed" ? "Indexação concluída." : `A indexação parou: ${job.message}`, job.status === "completed" ? "success" : "warning");
        setTimeout(() => panel.classList.add("hidden"), 1800);
      }
    } catch (error) {
      app.trackedJob = null;
      panel.classList.add("hidden");
      toast(error.message, "warning");
    }
  };
  poll();
}

async function createCollection(event) {
  event.preventDefault();
  const submit = $("#collectionForm button[type=submit]");
  submit.disabled = true;
  try {
    const collection = await api("/api/collections", {
      method: "POST",
      body: { name: $("#collectionName").value, description: $("#collectionDescription").value },
    });
    $("#collectionDialog").close();
    $("#collectionForm").reset();
    toast(`Coleção “${collection.name}” criada.`);
    await refreshState();
    selectView("all", "", collection.id);
  } catch (error) {
    toast(error.message, "warning");
  } finally {
    submit.disabled = false;
  }
}

async function savePrivacy(event) {
  event.preventDefault();
  try {
    const settings = await api("/api/settings", {
      method: "PATCH",
      body: {
        adult_visibility: $("#adultVisibility").value,
        sensitive_visibility: $("#sensitiveVisibility").value,
      },
    });
    app.state.settings = settings;
    app.revealed.clear();
    $("#privacyDialog").close();
    renderState();
    await loadImages(true);
    toast("Preferências de privacidade atualizadas.");
  } catch (error) {
    toast(error.message, "warning");
  }
}

function openSourceManager(rootId) {
  const root = app.state?.roots.find((item) => String(item.id) === String(rootId));
  if (!root) return;
  app.managedRoot = root;
  $("#sourceDialogName").textContent = root.label;
  $("#sourceDialogPath").textContent = root.path;
  $("#confirmSourceRemoval").checked = false;
  $("#removeSource").disabled = true;
  $("#sourceDialog").showModal();
}

async function changeSource(mode) {
  if (!app.managedRoot) return;
  const root = app.managedRoot;
  const button = mode === "catalog" ? $("#removeSource") : $("#disconnectSource");
  button.disabled = true;
  try {
    const result = await api(`/api/roots/${root.id}?mode=${mode}`, { method: "DELETE" });
    $("#sourceDialog").close();
    if (String(app.rootId) === String(root.id)) {
      app.rootId = "";
      app.view = mode === "disconnect" ? "offline" : "all";
    }
    app.managedRoot = null;
    await refreshState();
    await loadImages(true);
    if (mode === "disconnect") {
      toast(`A fonte “${root.label}” foi desconectada; ${result.image_count} itens continuam no índice.`);
    } else {
      toast(`A fonte “${root.label}” e ${result.image_count} itens foram removidos do catálogo. Os originais permanecem intactos.`);
    }
  } catch (error) {
    toast(error.message, "warning");
  } finally {
    button.disabled = mode === "catalog" && !$("#confirmSourceRemoval").checked;
  }
}

function closeMobilePanels() {
  $("#rail").classList.remove("open");
  $("#filters").classList.remove("open");
  $("#scrim").classList.remove("visible");
}

function openMobilePanel(panel) {
  closeMobilePanels();
  panel.classList.add("open");
  $("#scrim").classList.add("visible");
}

function bindEvents() {
  $$("[data-close]").forEach((button) => button.addEventListener("click", () => $(`#${button.dataset.close}`).close()));
  $$('dialog').forEach((dialog) => dialog.addEventListener("click", (event) => {
    if (event.target === dialog) dialog.close();
  }));

  $("#addFolderButton").addEventListener("click", addFolder);
  $("#addFolderMini").addEventListener("click", addFolder);
  $("#emptyAddFolder").addEventListener("click", addFolder);
  $("#manualPathButton").addEventListener("click", () => $("#pathDialog").showModal());
  $("#pathForm").addEventListener("submit", addManualPath);
  $("#scanAllButton").addEventListener("click", scanAll);
  $("#newCollectionMini").addEventListener("click", () => $("#collectionDialog").showModal());
  $("#collectionForm").addEventListener("submit", createCollection);
  $("#privacyButton").addEventListener("click", () => $("#privacyDialog").showModal());
  $("#privacyForm").addEventListener("submit", savePrivacy);
  $("#confirmSourceRemoval").addEventListener("change", (event) => { $("#removeSource").disabled = !event.target.checked; });
  $("#disconnectSource").addEventListener("click", () => changeSource("disconnect"));
  $("#removeSource").addEventListener("click", () => changeSource("catalog"));
  $("#saveDetails").addEventListener("click", saveDetails);
  $("#detailFavorite").addEventListener("click", toggleDetailFavorite);
  $("#revealFile").addEventListener("click", async () => {
    if (!app.detail) return;
    try {
      await api(`/api/images/${app.detail.id}/reveal`, { method: "POST", body: {} });
    } catch (error) { toast(error.message, "warning"); }
  });

  $("#searchInput").addEventListener("input", (event) => {
    clearTimeout(app.searchTimer);
    app.searchTimer = setTimeout(() => {
      app.query = event.target.value.trim();
      loadImages(true);
    }, 260);
  });
  $("#clearFilters").addEventListener("click", clearFilters);
  $("#formatFilter").addEventListener("change", (event) => { app.format = event.target.value; loadImages(true); });
  $("#ratingFilter").addEventListener("change", (event) => { app.rating = event.target.value; loadImages(true); });
  $("#widthFilter").addEventListener("change", (event) => { app.minWidth = event.target.value; loadImages(true); });
  $("#sortSelect").addEventListener("change", (event) => { app.sort = event.target.value; loadImages(true); });
  $("#orientationFilter").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-value]");
    if (!button) return;
    app.orientation = button.dataset.value;
    $$("#orientationFilter button").forEach((candidate) => candidate.classList.toggle("active", candidate === button));
    loadImages(true);
  });
  $("#loadMore").addEventListener("click", () => loadImages(false));

  $("#rail").addEventListener("click", (event) => {
    const manageRoot = event.target.closest("[data-manage-root]");
    if (manageRoot) {
      openSourceManager(manageRoot.dataset.manageRoot);
      return;
    }
    const root = event.target.closest("[data-root]");
    if (root) selectView("all", root.dataset.root, "");
    const collection = event.target.closest("[data-collection]");
    if (collection) selectView("all", "", collection.dataset.collection);
    const nav = event.target.closest("[data-view]");
    if (nav) selectView(nav.dataset.view);
  });
  $("#tagCloud").addEventListener("click", (event) => {
    const button = event.target.closest("[data-tag]");
    if (!button) return;
    app.tag = app.tag === button.dataset.tag ? "" : button.dataset.tag;
    renderState();
    loadImages(true);
  });

  $("#gallery").addEventListener("click", (event) => {
    const action = event.target.closest("[data-action]");
    if (!action) return;
    const imageId = Number(action.dataset.id);
    if (action.dataset.action === "clear-filters") clearFilters();
    if (action.dataset.action === "favorite") setFavorite(imageId);
    if (action.dataset.action === "reveal") {
      event.preventDefault();
      event.stopPropagation();
      app.revealed.add(imageId);
      renderGallery();
    }
    if (action.dataset.action === "details") {
      const item = app.items.find((candidate) => candidate.id === imageId);
      if (item && privacyMode(item) === "blur" && !app.revealed.has(imageId)) {
        app.revealed.add(imageId);
        renderGallery();
      } else {
        openDetails(imageId);
      }
    }
  });

  $("#detailMedia").addEventListener("click", (event) => {
    if (!event.target.closest('[data-action="reveal-detail"]') || !app.detail) return;
    app.revealed.add(app.detail.id);
    renderDetails();
    renderGallery();
  });

  $("#mobileMenu").addEventListener("click", () => openMobilePanel($("#rail")));
  $("#mobileFilter").addEventListener("click", () => openMobilePanel($("#filters")));
  $("#scrim").addEventListener("click", closeMobilePanels);
  $$('[data-action="home"]').forEach((button) => button.addEventListener("click", () => selectView("all")));
  document.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      $("#searchInput").focus();
    }
    if (event.key === "Escape") closeMobilePanels();
  });
}

async function initialize() {
  bindEvents();
  try {
    await refreshState();
    await loadImages(true);
  } catch (error) {
    toast(`Não foi possível iniciar o arquivo: ${error.message}`, "warning");
  }
}

initialize();
