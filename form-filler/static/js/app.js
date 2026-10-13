/**
 * FormFlow — Smart Document Form Filler
 * Main application controller
 */

(function () {
    "use strict";

    // ================================================================
    // State
    // ================================================================
    const state = {
        currentView: "form-filler",
        kb: { entries: {}, categorized: {}, categories: {}, count: 0 },
        form: null,         // { form_id, filename, page_count, fields, pages }
        currentPage: 0,
        activeFieldIdx: -1,
        wizardStep: 0,
        wizardData: {},
    };

    // ================================================================
    // Helpers
    // ================================================================
    function $(sel, ctx) { return (ctx || document).querySelector(sel); }
    function $$(sel, ctx) { return [...(ctx || document).querySelectorAll(sel)]; }

    function toast(msg, type = "") {
        const el = document.createElement("div");
        el.className = "toast " + type;
        el.textContent = msg;
        $("#toastContainer").appendChild(el);
        setTimeout(() => el.remove(), 3000);
    }

    async function api(path, opts = {}) {
        const res = await fetch("/api" + path, {
            headers: { "Content-Type": "application/json", ...opts.headers },
            ...opts,
        });
        return res.json();
    }

    async function apiUpload(path, file) {
        const fd = new FormData();
        fd.append("file", file);
        const res = await fetch("/api" + path, { method: "POST", body: fd });
        return res.json();
    }

    // ================================================================
    // Navigation
    // ================================================================
    function switchView(view) {
        state.currentView = view;
        $$(".view").forEach(v => v.classList.toggle("active", v.id === "view-" + view));
        $$(".nav-tab").forEach(t => t.classList.toggle("active", t.dataset.view === view));
        if (view === "knowledge-base") renderKB();
    }

    $$(".nav-tab").forEach(tab => {
        tab.addEventListener("click", () => switchView(tab.dataset.view));
    });

    // ================================================================
    // Knowledge Base
    // ================================================================
    async function loadKB() {
        state.kb = await api("/kb");
        $("#kbCountBadge").textContent = state.kb.count;
        return state.kb;
    }

    function renderKB() {
        const container = $("#kbCategories");
        const empty = $("#kbEmpty");
        const search = ($("#kbSearch").value || "").toLowerCase();

        if (state.kb.count === 0) {
            container.innerHTML = "";
            empty.classList.remove("hidden");
            return;
        }

        empty.classList.add("hidden");
        let html = "";

        for (const [catKey, catLabel] of Object.entries(state.kb.categories)) {
            const entries = (state.kb.categorized[catKey] || []).filter(e => {
                if (!search) return true;
                return e.key.toLowerCase().includes(search) ||
                    (e.value || "").toLowerCase().includes(search);
            });
            if (entries.length === 0) continue;

            html += `<div class="kb-category">
                <div class="kb-category-header">${catLabel} <span class="category-count">${entries.length}</span></div>`;

            for (const entry of entries) {
                html += `<div class="kb-entry" data-key="${entry.kb_key}">
                    <div class="kb-entry-key">${escHtml(entry.key)}</div>
                    <div class="kb-entry-value">${escHtml(entry.value || "—")}</div>
                    <div class="kb-entry-meta">${entry.source || ""}</div>
                    <div class="kb-entry-actions">
                        <button class="btn-icon kb-edit-btn" title="Edit">&#9998;</button>
                        <button class="btn-icon btn-danger kb-del-btn" title="Delete">&times;</button>
                    </div>
                </div>`;
            }
            html += `</div>`;
        }

        container.innerHTML = html;

        // Attach edit/delete handlers
        $$(".kb-edit-btn", container).forEach(btn => {
            btn.addEventListener("click", (e) => {
                e.stopPropagation();
                const row = btn.closest(".kb-entry");
                const key = row.dataset.key;
                const entry = state.kb.entries[key];
                if (!entry) return;
                startInlineEdit(row, key, entry);
            });
        });

        $$(".kb-del-btn", container).forEach(btn => {
            btn.addEventListener("click", async (e) => {
                e.stopPropagation();
                const key = btn.closest(".kb-entry").dataset.key;
                await api("/kb/entry/" + encodeURIComponent(key), { method: "DELETE" });
                toast("Entry deleted");
                await loadKB();
                renderKB();
            });
        });
    }

    function startInlineEdit(row, key, entry) {
        const valEl = row.querySelector(".kb-entry-value");
        const origHtml = valEl.innerHTML;
        valEl.innerHTML = `<div class="kb-entry-edit">
            <input type="text" value="${escAttr(entry.value)}" class="kb-inline-input">
            <button class="btn btn-sm btn-primary kb-save-inline">Save</button>
            <button class="btn btn-sm btn-ghost kb-cancel-inline">Cancel</button>
        </div>`;

        const input = valEl.querySelector(".kb-inline-input");
        input.focus();
        input.select();

        valEl.querySelector(".kb-cancel-inline").addEventListener("click", () => {
            valEl.innerHTML = origHtml;
        });

        const saveHandler = async () => {
            const newVal = input.value.trim();
            await api("/kb/entry", {
                method: "POST",
                body: JSON.stringify({ key: entry.key, value: newVal, source: "manual_edit" }),
            });
            toast("Updated: " + entry.key, "success");
            await loadKB();
            renderKB();
        };

        valEl.querySelector(".kb-save-inline").addEventListener("click", saveHandler);
        input.addEventListener("keydown", (e) => {
            if (e.key === "Enter") saveHandler();
            if (e.key === "Escape") { valEl.innerHTML = origHtml; }
        });
    }

    $("#kbSearch").addEventListener("input", () => renderKB());

    // Add entry button
    $("#btnAddEntry").addEventListener("click", () => {
        const container = $("#kbCategories");
        const form = document.createElement("div");
        form.className = "kb-entry";
        form.style.background = "var(--primary-light)";
        form.innerHTML = `
            <input type="text" placeholder="Field name" class="kb-new-key" style="width:200px;flex-shrink:0">
            <input type="text" placeholder="Value" class="kb-new-val" style="flex:1">
            <button class="btn btn-sm btn-primary kb-new-save">Add</button>
            <button class="btn btn-sm btn-ghost kb-new-cancel">Cancel</button>`;
        container.prepend(form);

        form.querySelector(".kb-new-key").focus();

        form.querySelector(".kb-new-cancel").addEventListener("click", () => form.remove());

        const save = async () => {
            const key = form.querySelector(".kb-new-key").value.trim();
            const val = form.querySelector(".kb-new-val").value.trim();
            if (!key) return;
            await api("/kb/entry", {
                method: "POST",
                body: JSON.stringify({ key, value: val, source: "manual" }),
            });
            toast("Added: " + key, "success");
            form.remove();
            await loadKB();
            renderKB();
        };

        form.querySelector(".kb-new-save").addEventListener("click", save);
        form.querySelectorAll("input").forEach(inp => {
            inp.addEventListener("keydown", (e) => { if (e.key === "Enter") save(); });
        });
    });

    // ================================================================
    // KB Upload
    // ================================================================
    function openKBUpload() {
        $("#kbUploadModal").classList.remove("hidden");
        $("#kbUploadResult").classList.add("hidden");
    }

    function closeKBUpload() {
        $("#kbUploadModal").classList.add("hidden");
    }

    async function handleKBUpload(file) {
        toast("Parsing " + file.name + "...");
        const result = await apiUpload("/kb/upload", file);
        if (result.error) {
            toast(result.error, "error");
            return;
        }

        // Show conflicts
        if (result.conflicts && result.conflicts.length > 0) {
            for (const c of result.conflicts) {
                await resolveConflict(c);
            }
        }

        // Show extracted entries
        $("#kbUploadCount").textContent = result.extracted;
        let listHtml = "";
        for (const [k, v] of Object.entries(result.entries || {})) {
            listHtml += `<div class="upload-result-entry">
                <span class="key">${escHtml(k)}</span>
                <span class="val">${escHtml(v)}</span>
            </div>`;
        }
        $("#kbUploadList").innerHTML = listHtml;
        $("#kbUploadResult").classList.remove("hidden");

        toast(result.extracted + " entries added to KB", "success");
        await loadKB();
    }

    $("#btnUploadKB").addEventListener("click", openKBUpload);
    $("#btnUploadKBInline").addEventListener("click", openKBUpload);
    $("#btnCloseKBUpload").addEventListener("click", closeKBUpload);
    $("#btnCancelKBUpload").addEventListener("click", closeKBUpload);

    $("#btnBrowseKB").addEventListener("click", () => $("#kbFileInput").click());
    $("#kbFileInput").addEventListener("change", (e) => {
        if (e.target.files[0]) handleKBUpload(e.target.files[0]);
    });

    // Drag & drop for KB upload
    const kbZone = $("#kbUploadZone");
    kbZone.addEventListener("dragover", (e) => { e.preventDefault(); kbZone.classList.add("dragover"); });
    kbZone.addEventListener("dragleave", () => kbZone.classList.remove("dragover"));
    kbZone.addEventListener("drop", (e) => {
        e.preventDefault();
        kbZone.classList.remove("dragover");
        if (e.dataTransfer.files[0]) handleKBUpload(e.dataTransfer.files[0]);
    });

    // ================================================================
    // Conflict Resolution
    // ================================================================
    function resolveConflict(conflict) {
        return new Promise((resolve) => {
            const modal = $("#conflictModal");
            modal.classList.remove("hidden");

            $("#conflictBody").innerHTML = `
                <p style="margin-bottom:12px">The field <strong>${escHtml(conflict.field)}</strong> has conflicting values:</p>
                <div class="conflict-values">
                    <div class="conflict-option" data-choice="old">
                        <div class="conflict-label">Current (from ${escHtml(conflict.old_source || "unknown")})</div>
                        <div class="conflict-value">${escHtml(conflict.old_value)}</div>
                    </div>
                    <div class="conflict-option" data-choice="new">
                        <div class="conflict-label">New (from ${escHtml(conflict.new_source || "unknown")})</div>
                        <div class="conflict-value">${escHtml(conflict.new_value)}</div>
                    </div>
                </div>`;

            let chosen = "new";
            $$(".conflict-option", modal).forEach(opt => {
                opt.addEventListener("click", () => {
                    $$(".conflict-option", modal).forEach(o => o.classList.remove("selected"));
                    opt.classList.add("selected");
                    chosen = opt.dataset.choice;
                });
            });
            // Select new by default
            $(".conflict-option[data-choice='new']", modal).classList.add("selected");

            $("#conflictFooter").innerHTML = `
                <button class="btn btn-ghost conflict-dismiss">Skip</button>
                <button class="btn btn-primary conflict-apply">Apply Selected</button>`;

            const close = async (apply) => {
                modal.classList.add("hidden");
                if (apply && chosen === "old") {
                    // Revert to old value
                    await api("/kb/entry", {
                        method: "POST",
                        body: JSON.stringify({
                            key: conflict.field,
                            value: conflict.old_value,
                            source: conflict.old_source,
                        }),
                    });
                }
                resolve(chosen);
            };

            $(".conflict-dismiss", modal).addEventListener("click", () => close(false));
            $(".conflict-apply", modal).addEventListener("click", () => close(true));
        });
    }

    // ================================================================
    // Form Upload & Filling
    // ================================================================
    const uploadArea = $("#formUploadArea");
    const uploadContent = $(".upload-content", uploadArea);
    const workspace = $("#formWorkspace");

    $("#btnBrowseForm").addEventListener("click", () => $("#formFileInput").click());
    uploadContent.addEventListener("click", () => $("#formFileInput").click());

    // Drag & drop
    uploadContent.addEventListener("dragover", (e) => {
        e.preventDefault();
        uploadContent.classList.add("dragover");
    });
    uploadContent.addEventListener("dragleave", () => uploadContent.classList.remove("dragover"));
    uploadContent.addEventListener("drop", (e) => {
        e.preventDefault();
        uploadContent.classList.remove("dragover");
        if (e.dataTransfer.files[0]) loadForm(e.dataTransfer.files[0]);
    });

    $("#formFileInput").addEventListener("change", (e) => {
        if (e.target.files[0]) loadForm(e.target.files[0]);
    });

    async function loadForm(file) {
        toast("Analyzing form...");
        const result = await apiUpload("/form/upload", file);
        if (result.error) {
            toast(result.error, "error");
            return;
        }

        state.form = result;
        state.currentPage = 0;
        state.activeFieldIdx = -1;

        uploadArea.classList.add("hidden");
        workspace.classList.remove("hidden");

        $("#formFilename").textContent = result.filename;
        renderFormPage();
        renderFieldList();
        updateFieldStats();

        // Auto-focus first empty field
        const firstEmpty = result.fields.findIndex(f => !f.filled_value);
        if (firstEmpty >= 0) activateField(firstEmpty);

        toast(result.fields.length + " fields detected", "success");
    }

    function renderFormPage() {
        const page = state.form.pages[state.currentPage];
        const pageContent = $("#formPageContent");

        let text = escHtml(page.text || "(Empty page)");

        // Highlight fields on this page
        const pageFields = state.form.fields.filter(f => f.page === state.currentPage);
        for (const field of pageFields) {
            const fieldIdx = state.form.fields.indexOf(field);
            const escapedName = escHtml(field.name);
            const statusClass = field.filled_value ? (field.flagged ? "flagged" : "filled") : "";
            const activeClass = fieldIdx === state.activeFieldIdx ? "active" : "";

            // Try to highlight the field name in the text
            const namePattern = escapedName.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
            const regex = new RegExp("(" + namePattern + ")", "i");
            if (regex.test(text)) {
                text = text.replace(regex,
                    `<span class="field-highlight ${statusClass} ${activeClass}" data-field-idx="${fieldIdx}">$1</span>`
                );
            }
        }

        pageContent.innerHTML = `<div class="page-render">${text}</div>`;

        // Update page indicator
        $("#pageIndicator").textContent = (state.currentPage + 1) + " / " + state.form.page_count;

        // Attach click handlers to highlights
        $$(".field-highlight", pageContent).forEach(el => {
            el.addEventListener("click", () => {
                activateField(parseInt(el.dataset.fieldIdx));
            });
        });
    }

    function renderFieldList() {
        const list = $("#fieldList");
        let html = "";

        state.form.fields.forEach((field, idx) => {
            const isFilled = !!field.filled_value;
            const isFlagged = !!field.flagged;
            const isActive = idx === state.activeFieldIdx;
            const statusClass = isFlagged ? "flagged" : (isFilled ? "filled" : "empty");
            const sourceClass = field.fill_source === "knowledge_base" ? "kb" :
                (field.fill_source === "manual" || field.fill_source === "edited" ? "manual" : "none");
            const sourceLabel = field.fill_source === "knowledge_base" ? "KB" :
                (field.fill_source === "manual" || field.fill_source === "edited" ? "Manual" : "Empty");

            html += `<div class="field-card ${statusClass} ${isActive ? "active" : ""}" data-idx="${idx}">
                <div class="field-card-header">
                    <span class="field-name">${escHtml(field.name)}</span>
                    <span class="field-source ${sourceClass}">${sourceLabel}</span>
                </div>
                <div class="field-input-row">
                    <input type="text" value="${escAttr(field.filled_value || "")}"
                           placeholder="Enter value..."
                           data-idx="${idx}"
                           class="field-value-input">
                    <button class="btn-icon field-accept-btn" data-idx="${idx}" title="Accept & next">&#10003;</button>
                </div>
                <div class="field-page-badge">Page ${field.page + 1}${field.confidence > 0 && field.confidence < 1 ? " &middot; " + Math.round(field.confidence * 100) + "% match" : ""}</div>
            </div>`;
        });

        list.innerHTML = html;

        // Attach handlers
        $$(".field-card", list).forEach(card => {
            card.addEventListener("click", (e) => {
                if (e.target.tagName === "INPUT" || e.target.tagName === "BUTTON") return;
                activateField(parseInt(card.dataset.idx));
            });
        });

        $$(".field-value-input", list).forEach(input => {
            input.addEventListener("focus", () => {
                activateField(parseInt(input.dataset.idx));
            });

            input.addEventListener("input", (e) => {
                const idx = parseInt(input.dataset.idx);
                const field = state.form.fields[idx];
                field.filled_value = input.value;
                field.fill_source = field.fill_source === "knowledge_base" ? "edited" : "manual";
                updateFieldStats();
            });

            input.addEventListener("keydown", (e) => {
                if (e.key === "Enter" || e.key === "Tab") {
                    e.preventDefault();
                    const idx = parseInt(input.dataset.idx);
                    acceptAndAdvance(idx);
                }
            });
        });

        $$(".field-accept-btn", list).forEach(btn => {
            btn.addEventListener("click", (e) => {
                e.stopPropagation();
                acceptAndAdvance(parseInt(btn.dataset.idx));
            });
        });
    }

    function activateField(idx) {
        if (idx < 0 || idx >= state.form.fields.length) return;
        state.activeFieldIdx = idx;
        const field = state.form.fields[idx];

        // Switch to the field's page if needed
        if (field.page !== state.currentPage) {
            state.currentPage = field.page;
            renderFormPage();
        }

        // Update visual state
        $$(".field-card").forEach(c => c.classList.remove("active"));
        const card = $(`.field-card[data-idx="${idx}"]`);
        if (card) {
            card.classList.add("active");
            card.scrollIntoView({ behavior: "smooth", block: "nearest" });
            const input = card.querySelector(".field-value-input");
            if (input) {
                input.focus();
                input.select();
            }
        }

        // Update highlights on form page
        $$(".field-highlight").forEach(h => h.classList.remove("active"));
        const highlight = $(`.field-highlight[data-field-idx="${idx}"]`);
        if (highlight) {
            highlight.classList.add("active");
            highlight.scrollIntoView({ behavior: "smooth", block: "center" });
        }
    }

    function acceptAndAdvance(idx) {
        const field = state.form.fields[idx];
        const input = $(`.field-value-input[data-idx="${idx}"]`);
        if (input) {
            field.filled_value = input.value;
            if (!field.fill_source || field.fill_source === "none") {
                field.fill_source = "manual";
            }
        }

        // Update card visual
        const card = $(`.field-card[data-idx="${idx}"]`);
        if (card) {
            card.classList.remove("empty");
            card.classList.add("filled");
        }

        updateFieldStats();
        renderFormPage();

        // Advance to next empty field
        let nextIdx = -1;
        for (let i = idx + 1; i < state.form.fields.length; i++) {
            if (!state.form.fields[i].filled_value) {
                nextIdx = i;
                break;
            }
        }
        // Wrap around
        if (nextIdx === -1) {
            for (let i = 0; i < idx; i++) {
                if (!state.form.fields[i].filled_value) {
                    nextIdx = i;
                    break;
                }
            }
        }

        if (nextIdx >= 0) {
            activateField(nextIdx);
        } else {
            // All filled — trigger sanity check
            toast("All fields filled!", "success");
            runSanityCheck();
        }
    }

    function updateFieldStats() {
        if (!state.form) return;
        const fields = state.form.fields;
        const filled = fields.filter(f => f.filled_value).length;
        const flagged = fields.filter(f => f.flagged).length;
        const empty = fields.length - filled;

        $("#statFilled").textContent = filled + " filled";
        $("#statEmpty").textContent = empty + " empty";
        $("#statFlagged").textContent = flagged + " flagged";
    }

    // Page navigation
    $("#btnPrevPage").addEventListener("click", () => {
        if (state.currentPage > 0) {
            state.currentPage--;
            renderFormPage();
        }
    });

    $("#btnNextPage").addEventListener("click", () => {
        if (state.form && state.currentPage < state.form.page_count - 1) {
            state.currentPage++;
            renderFormPage();
        }
    });

    // ================================================================
    // Sanity Checks
    // ================================================================
    async function runSanityCheck(page) {
        const body = { fields: state.form.fields };
        if (page !== undefined) body.page = page;

        const result = await api("/form/sanity-check", {
            method: "POST",
            body: JSON.stringify(body),
        });

        showSanityResults(result.issues);
        return result.issues;
    }

    function showSanityResults(issues) {
        const panel = $("#sanityPanel");
        const body = $("#sanityBody");

        panel.classList.remove("hidden");

        if (!issues || issues.length === 0) {
            body.innerHTML = `<div class="sanity-all-clear">&#10003; All checks passed — looking good!</div>`;
            // Flag no fields
            if (state.form) {
                state.form.fields.forEach(f => { f.flagged = false; });
                renderFieldList();
                renderFormPage();
            }
            return;
        }

        // Mark flagged fields
        if (state.form) {
            state.form.fields.forEach(f => { f.flagged = false; });
            for (const issue of issues) {
                const field = state.form.fields.find(f =>
                    f.name.toLowerCase() === issue.field.toLowerCase()
                );
                if (field) field.flagged = true;
            }
            renderFieldList();
            renderFormPage();
            updateFieldStats();
        }

        let html = "";
        for (const issue of issues) {
            const iconChar = issue.severity === "error" ? "&#10007;" :
                (issue.severity === "warning" ? "&#9888;" : "&#8505;");
            html += `<div class="sanity-item">
                <div class="sanity-icon ${issue.severity}">${iconChar}</div>
                <div class="sanity-detail">
                    <div class="sanity-field">${escHtml(issue.field)}</div>
                    <div class="sanity-message">${escHtml(issue.message)}</div>
                </div>
            </div>`;
        }
        body.innerHTML = html;
    }

    $("#btnCheckAll").addEventListener("click", () => runSanityCheck());
    $("#btnCheckPage").addEventListener("click", () => runSanityCheck(state.currentPage));
    $("#btnCloseSanity").addEventListener("click", () => {
        $("#sanityPanel").classList.add("hidden");
    });

    // ================================================================
    // Save Form & Update KB
    // ================================================================
    $("#btnSaveForm").addEventListener("click", async () => {
        const result = await api("/form/fill", {
            method: "POST",
            body: JSON.stringify({
                fields: state.form.fields,
                save_to_kb: true,
            }),
        });

        if (result.issues && result.issues.length > 0) {
            showSanityResults(result.issues);
            toast("Saved with " + result.issues.length + " warnings", "warning");
        } else {
            toast("Saved! Knowledge base updated.", "success");
        }

        await loadKB();
    });

    // ================================================================
    // Setup Wizard
    // ================================================================
    const WIZARD_STEPS = [
        {
            title: "Personal Information",
            description: "Basic identity information used on most forms.",
            fields: [
                { key: "First Name", placeholder: "John" },
                { key: "Last Name", placeholder: "Doe" },
                { key: "Date of Birth", placeholder: "MM/DD/YYYY", type: "text" },
                { key: "Gender", placeholder: "Male / Female / Other" },
            ],
        },
        {
            title: "Contact Details",
            description: "How you can be reached.",
            fields: [
                { key: "Email", placeholder: "john@example.com", type: "email" },
                { key: "Phone", placeholder: "(555) 123-4567", type: "tel" },
                { key: "Mobile Phone", placeholder: "(555) 987-6543", type: "tel" },
            ],
        },
        {
            title: "Address",
            description: "Your primary mailing address.",
            fields: [
                { key: "Street Address", placeholder: "123 Main St" },
                { key: "City", placeholder: "Springfield" },
                { key: "State", placeholder: "IL" },
                { key: "ZIP Code", placeholder: "62701" },
                { key: "Country", placeholder: "United States" },
            ],
        },
        {
            title: "Employment",
            description: "Current job details — used on many official forms.",
            fields: [
                { key: "Employer", placeholder: "Acme Corp" },
                { key: "Job Title", placeholder: "Software Engineer" },
                { key: "Work Phone", placeholder: "(555) 456-7890", type: "tel" },
                { key: "Work Email", placeholder: "john@acme.com", type: "email" },
            ],
        },
        {
            title: "Additional IDs",
            description: "Common identification numbers. Leave blank to skip.",
            fields: [
                { key: "SSN", placeholder: "XXX-XX-XXXX" },
                { key: "Driver License Number", placeholder: "" },
                { key: "Passport Number", placeholder: "" },
            ],
        },
    ];

    function renderWizardStep() {
        const step = WIZARD_STEPS[state.wizardStep];
        const body = $("#wizardBody");

        let html = `<div class="wizard-step">
            <h3>${step.title}</h3>
            <p>${step.description}</p>`;

        for (const field of step.fields) {
            const savedVal = state.wizardData[field.key] || "";
            html += `<div class="wizard-field">
                <label>${field.key}</label>
                <input type="${field.type || "text"}"
                       placeholder="${field.placeholder || ""}"
                       value="${escAttr(savedVal)}"
                       data-key="${escAttr(field.key)}"
                       class="wizard-input">
            </div>`;
        }

        html += `</div>`;
        body.innerHTML = html;

        // Focus first empty input
        const inputs = $$(".wizard-input", body);
        const firstEmpty = inputs.find(i => !i.value);
        if (firstEmpty) firstEmpty.focus();
        else if (inputs[0]) inputs[0].focus();

        // Enter key advances
        inputs.forEach(input => {
            input.addEventListener("keydown", (e) => {
                if (e.key === "Enter") {
                    e.preventDefault();
                    const idx = inputs.indexOf(input);
                    if (idx < inputs.length - 1) {
                        inputs[idx + 1].focus();
                    } else {
                        advanceWizard();
                    }
                }
            });
        });

        // Update progress
        const pct = ((state.wizardStep + 1) / WIZARD_STEPS.length) * 100;
        $("#wizardProgress").style.width = pct + "%";
        $("#wizardStepLabel").textContent = `Step ${state.wizardStep + 1} of ${WIZARD_STEPS.length}`;
        $("#wizardBack").disabled = state.wizardStep === 0;
        $("#wizardNext").textContent = state.wizardStep === WIZARD_STEPS.length - 1 ? "Finish" : "Next";
    }

    function collectWizardInputs() {
        $$(".wizard-input").forEach(input => {
            const key = input.dataset.key;
            const val = input.value.trim();
            if (val) state.wizardData[key] = val;
        });
    }

    async function advanceWizard() {
        collectWizardInputs();

        if (state.wizardStep < WIZARD_STEPS.length - 1) {
            state.wizardStep++;
            renderWizardStep();
        } else {
            // Finish — save to KB
            await api("/kb/bulk", {
                method: "POST",
                body: JSON.stringify({ entries: state.wizardData, source: "setup_wizard" }),
            });
            $("#wizardOverlay").classList.add("hidden");
            toast("Knowledge base initialized!", "success");
            await loadKB();
        }
    }

    $("#wizardNext").addEventListener("click", advanceWizard);
    $("#wizardBack").addEventListener("click", () => {
        collectWizardInputs();
        if (state.wizardStep > 0) {
            state.wizardStep--;
            renderWizardStep();
        }
    });
    $("#wizardSkip").addEventListener("click", () => {
        collectWizardInputs();
        // Save whatever was entered
        const hasData = Object.values(state.wizardData).some(v => v);
        if (hasData) {
            api("/kb/bulk", {
                method: "POST",
                body: JSON.stringify({ entries: state.wizardData, source: "setup_wizard" }),
            }).then(() => loadKB());
        }
        $("#wizardOverlay").classList.add("hidden");
    });

    $("#btnRunWizard").addEventListener("click", () => {
        state.wizardStep = 0;
        state.wizardData = {};
        renderWizardStep();
        $("#wizardOverlay").classList.remove("hidden");
    });

    // ================================================================
    // Escape Helpers
    // ================================================================
    function escHtml(s) {
        const div = document.createElement("div");
        div.textContent = s || "";
        return div.innerHTML;
    }

    function escAttr(s) {
        return (s || "").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
    }

    // ================================================================
    // Init
    // ================================================================
    async function init() {
        await loadKB();
        renderKB();

        // Show wizard if KB is empty
        if (state.kb.count === 0) {
            state.wizardStep = 0;
            state.wizardData = {};
            renderWizardStep();
            $("#wizardOverlay").classList.remove("hidden");
        }
    }

    init();
})();
