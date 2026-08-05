(function () {
    "use strict";

    const focusState = {
        id: null,
        start: null,
        end: null,
        value: null,
        checked: null,
        selectedValues: null,
    };
    let rowClickTimer = null;
    let speechEnabled = false;
    let lastSpokenText = "";
    const chatRecorders = new WeakMap();
    const voiceRecorders = new WeakMap();
    const observedWorkspaceTabs = new WeakSet();
    let seasonalLogoTimer = null;
    let monacoPromise = null;
    let plotlyPromise = null;
    let qzPromise = null;
    let qzConfigured = false;
    let qzPrintQueue = Promise.resolve();
    let pendingColumnPopup = null;
    const observedWorkspaceToolbars = new WeakSet();

    document.addEventListener("change", event => {
        const model = event.target.closest?.("[data-reference-model]");
        if (!model) return;
        const widget = model.closest("[data-reference-widget]");
        const input = widget?.querySelector("[data-reference-input]");
        const hidden = widget?.querySelector("[data-reference-hidden]");
        if (!hidden) return;
        input.value = "";
        hidden.value = "";
        htmx.trigger(hidden, "change");
    });

    document.addEventListener("click", event => {
        const choice = event.target.closest?.("[data-reference-choice]");
        if (!choice) return;
        const widget = choice.closest("[data-reference-widget]");
        const model = widget?.querySelector("[data-reference-model]");
        const input = widget?.querySelector("[data-reference-input]");
        const hidden = widget?.querySelector("[data-reference-hidden]");
        if (!model || !input || !hidden) return;
        event.preventDefault();
        input.value = choice.dataset.referenceTitle;
        hidden.value = model.value + "," + choice.dataset.referenceChoice;
        htmx.trigger(hidden, "change");
    });

    function syncURLWidget(widget) {
        const input = widget?.querySelector("[data-url-input]");
        const link = widget?.querySelector("[data-url-open]");
        if (!input || !link) return;
        const value = input.value || "";
        const href = value ? (widget.dataset.urlPrefix || "") + value : "";
        link.hidden = !value;
        link.title = value;
        if (href) {
            link.setAttribute("href", href);
        } else {
            link.removeAttribute("href");
        }
    }

    function activateNumericEditor(display, deferFocus=false) {
        const widget = display?.closest("[data-numeric-widget]");
        const editor = widget?.querySelector("[data-numeric-editor]");
        if (!editor || editor.disabled || editor.readOnly) return false;
        display.hidden = true;
        editor.hidden = false;
        if (deferFocus) {
            window.setTimeout(() => {
                if (editor.isConnected && !editor.hidden) editor.focus();
            });
        } else {
            editor.focus();
        }
        return true;
    }

    document.addEventListener("click", event => {
        const link = event.target.closest?.("[data-url-open]");
        if (!link) return;
        syncURLWidget(link.closest("[data-url-widget]"));
        if (!link.getAttribute("href")) {
            event.preventDefault();
        }
    }, true);

    function easterSundayDate(year) {
        const a = year % 19;
        const b = (year / 100) | 0;
        const c = year % 100;
        const d = (b / 4) | 0;
        const e = b % 4;
        const f = ((b + 8) / 25) | 0;
        const g = ((b - f + 1) / 3) | 0;
        const h = (19 * a + b - d - g + 15) % 30;
        const i = (c / 4) | 0;
        const k = c % 4;
        const l = (32 + 2 * e + 2 * i - h - k) % 7;
        const m = ((a + 11 * h + 22 * l) / 451) | 0;
        const month = ((h + l - 7 * m + 114) / 31) | 0;
        const day = ((h + l - 7 * m + 114) % 31) + 1;
        return new Date(year, month - 1, day);
    }

    function seasonalLogoSource(date) {
        const month = date.getMonth() + 1;
        const day = date.getDate();
        if (month === 1 && day >= 11 && day <= 15) {
            return "/cassini-private-images/logo-birthday.png";
        }
        if (month === 12 || (month === 1 && day < 7)) {
            return "/cassini-private-images/logo-christmas.png";
        }
        if ((month === 10 && day >= 30) ||
                (month === 11 && day <= 2)) {
            return "/cassini-private-images/logo-halloween.png";
        }
        const today = new Date(
            date.getFullYear(), date.getMonth(), date.getDate());
        const easter = easterSundayDate(today.getFullYear());
        const palmSunday = new Date(easter);
        const easterMonday = new Date(easter);
        palmSunday.setDate(easter.getDate() - 7);
        easterMonday.setDate(easter.getDate() + 1);
        if (today >= palmSunday && today <= easterMonday) {
            return "/cassini-private-images/logo-easter.png";
        }
        if (month === 3 && day === 8) {
            return "/cassini-private-images/logo-women.png";
        }
        return "/cassini-private-images/logo.png";
    }

    function applySeasonalLogo() {
        const logo = document.querySelector("[data-seasonal-logo]");
        if (logo) {
            logo.src = seasonalLogoSource(new Date());
        }
    }

    function initializeSeasonalLogo() {
        applySeasonalLogo();
        if (seasonalLogoTimer === null) {
            seasonalLogoTimer = window.setInterval(
                applySeasonalLogo, 8 * 60 * 60 * 1000);
        }
    }

    function tr(source, variables) {
        const element = document.querySelector(
            "meta[name='cassini-translations']");
        let translations = {};
        if (element) {
            try {
                translations = JSON.parse(element.content || "{}");
            } catch (error) {
                translations = {};
            }
        }
        let value = translations[source] || source;
        Object.entries(variables || {}).forEach(([name, replacement]) => {
            value = value.replaceAll("%(" + name + ")s", replacement);
        });
        return value;
    }

    const shortcutDefinitions = Object.freeze([
        {shortcut: "Alt+N", label: tr("New"), action: "new",
            key: "n", alt: true, scope: "tab"},
        {shortcut: "Ctrl+S", label: tr("Save"), action: "save",
            key: "s", ctrl: true, scope: "tab"},
        {shortcut: "Ctrl+L", label: tr("Switch"), action: "switch",
            key: "l", ctrl: true, scope: "tab"},
        {shortcut: "Ctrl+R", label: tr("Reload/Undo"), action: "reload",
            key: "r", ctrl: true, scope: "tab"},
        {shortcut: "Ctrl+Shift+D", label: tr("Duplicate"),
            action: "duplicate", key: "d", ctrl: true, shift: true,
            scope: "tab"},
        {shortcut: "Ctrl+D", label: tr("Delete"), action: "delete",
            key: "d", ctrl: true, scope: "tab"},
        {shortcut: "Ctrl+Up", label: tr("Previous"), action: "previous",
            key: "arrowup", ctrl: true, scope: "tab"},
        {shortcut: "Ctrl+Down", label: tr("Next"), action: "next",
            key: "arrowdown", ctrl: true, scope: "tab"},
        {shortcut: "Ctrl+F", label: tr("Search"), action: "search",
            key: "f", ctrl: true, scope: "tab"},
        {shortcut: "Alt+W", label: tr("Close Tab"), action: "close",
            key: "w", alt: true, scope: "tab"},
        {shortcut: "Ctrl+Shift+T", label: tr("Attachment"),
            action: "attach", key: "t", ctrl: true, shift: true,
            scope: "tab"},
        {shortcut: "Ctrl+Shift+O", label: tr("Note"), action: "note",
            key: "o", ctrl: true, shift: true, scope: "tab"},
        {shortcut: "Ctrl+E", label: tr("Action"), action: "action",
            key: "e", ctrl: true, scope: "tab"},
        {shortcut: "Ctrl+Shift+R", label: tr("Relate"), action: "relate",
            key: "r", ctrl: true, shift: true, scope: "tab"},
        {shortcut: "Ctrl+P", label: tr("Print"), action: "print",
            key: "p", ctrl: true, scope: "tab"},
        {shortcut: "Alt+PageUp", label: tr("Previous tab"),
            action: "previous-tab", key: "pageup", alt: true,
            scope: "global"},
        {shortcut: "Alt+PageDown", label: tr("Next tab"),
            action: "next-tab", key: "pagedown", alt: true,
            scope: "global"},
        {shortcut: "Ctrl+K", label: tr("Global search"),
            action: "global-search", key: "k", ctrl: true,
            scope: "global"},
        {shortcut: "F1", label: tr("Show this help"), action: "help",
            key: "f1", scope: "global"},
        {shortcut: "Ctrl+F1", label: tr("Show/Hide access keys"),
            action: "accesskeys", key: "f1", ctrl: true,
            scope: "global"},
    ]);
    let workspaceStickyFrame = null;
    let focusSearchAfterSwap = false;
    const workspaceResizeObserver = (
        typeof ResizeObserver === "function" ?
            new ResizeObserver(syncWorkspaceStickyOffsets) : null);
    let observedSidebar = null;
    let sidebarWidthTimer = null;
    const sidebarResizeObserver = (
        typeof ResizeObserver === "function" ?
            new ResizeObserver(function (entries) {
                if (entries.some(entry => entry.target === observedSidebar)) {
                    captureSidebarWidth(true);
                }
            }) : null);
    let surflyPromise = null;

    function rememberFocus() {
        const element = document.activeElement;
        if (!element || !element.id) {
            focusState.id = null;
            focusState.start = null;
            focusState.end = null;
            focusState.value = null;
            focusState.checked = null;
            focusState.selectedValues = null;
            return;
        }
        focusState.id = element.id;
        focusState.start = element.selectionStart;
        focusState.end = element.selectionEnd;
        focusState.value = "value" in element ? element.value : null;
        focusState.checked = "checked" in element ? element.checked : null;
        focusState.selectedValues = (
            element instanceof HTMLSelectElement && element.multiple ?
                Array.from(element.selectedOptions, option => option.value) :
                null);
    }

    function restoreFocus() {
        if (!focusState.id) {
            return false;
        }
        const active = document.activeElement;
        if (active && active !== document.body && active.isConnected &&
                active.id && active.id !== focusState.id) {
            return false;
        }
        const element = document.getElementById(focusState.id);
        if (!element) {
            return false;
        }
        if (focusState.selectedValues !== null &&
                element instanceof HTMLSelectElement && element.multiple) {
            const selected = new Set(focusState.selectedValues);
            for (const option of element.options) {
                option.selected = selected.has(option.value);
            }
        } else if (focusState.value !== null && "value" in element) {
            element.value = focusState.value;
        }
        if (focusState.checked !== null && "checked" in element) {
            element.checked = focusState.checked;
        }
        element.focus({preventScroll: true});
        if (element.setSelectionRange &&
                focusState.start !== null && focusState.end !== null) {
            element.setSelectionRange(focusState.start, focusState.end);
        }
        return true;
    }

    function isVisible(element) {
        return Boolean(element && element.getClientRects().length &&
            getComputedStyle(element).visibility !== "hidden");
    }

    function x2manyFocusSelector(trigger) {
        if (trigger?.matches?.(
                "[data-x2many-inline-new], [data-editable-tree-new]")) {
            return trigger.getAttribute("hx-target");
        }
        return null;
    }

    function focusNewX2ManyRow(selector) {
        if (!selector) {
            return;
        }
        window.requestAnimationFrame(function () {
            const relation = document.querySelector(selector);
            const row = relation?.querySelector(
                ".vs-x2many-row-current");
            const controls = Array.from(row?.querySelectorAll(
                ".vs-field input, .vs-field select, " +
                ".vs-field textarea") || []).filter(element =>
                    isVisible(element) && !element.disabled &&
                    !element.readOnly && element.type !== "hidden" &&
                    element.tabIndex !== -1);
            const control = controls.find(
                element => element.autofocus) || controls[0];
            control?.focus({preventScroll: true});
        });
    }

    function focusInitialForm(forceModal=false) {
        const modalScreen = Array.from(document.querySelectorAll(
            forceModal ? ".vs-modal-backdrop .vs-screen" :
                ".vs-modal-backdrop " +
                ".vs-screen[data-initial-focus='true']"))
            .filter(isVisible).pop();
        const screen = modalScreen || document.querySelector(
            "#active-panel .vs-screen[data-initial-focus='true']");
        const form = screen?.querySelector(".vs-form");
        if (!form || !isVisible(form)) {
            screen?.setAttribute("data-initial-focus", "false");
            return;
        }
        screen.dataset.initialFocus = "false";
        if (forceModal && modalScreen &&
                form.contains(document.activeElement)) {
            return;
        }
        const controls = Array.from(form.querySelectorAll(
            "input, select, textarea")).filter(element =>
                isVisible(element) && !element.disabled &&
                !element.readOnly && element.type !== "hidden" &&
                element.tabIndex !== -1);
        controls.sort(function (left, right) {
            const leftTab = left.hasAttribute("tabindex");
            const rightTab = right.hasAttribute("tabindex");
            if (leftTab && rightTab) {
                return left.tabIndex - right.tabIndex;
            }
            return leftTab ? -1 : rightTab ? 1 : 0;
        });
        const cursor = form.dataset.formCursor;
        const cursorField = cursor ? form.querySelector(
            ".vs-field[data-field=\"" + CSS.escape(cursor) + "\"]") : null;
        let control = cursorField ? controls.find(
            element => cursorField.contains(element)) : null;
        control = control || controls.find(
            element => element.autofocus) || controls[0];
        control?.focus({preventScroll: true});
    }

    function scheduleInitialFormFocus() {
        window.setTimeout(focusInitialForm, 50);
    }

    const initialFormFocusObserver = (
        typeof MutationObserver === "function" ?
            new MutationObserver(function () {
                if (document.querySelector(
                        ".vs-screen[data-initial-focus='true']")) {
                    scheduleInitialFormFocus();
                }
            }) : null);
    initialFormFocusObserver?.observe(
        document.documentElement, {childList: true, subtree: true});
    scheduleInitialFormFocus();

    function padTemporal(value, length=2) {
        return String(value).padStart(length, "0");
    }

    function temporalFormat(date, format) {
        const hour = date.getHours();
        const replacements = {
            "%Y": padTemporal(date.getFullYear(), 4),
            "%y": padTemporal(date.getFullYear() % 100),
            "%m": padTemporal(date.getMonth() + 1),
            "%d": padTemporal(date.getDate()),
            "%H": padTemporal(hour),
            "%I": padTemporal((hour % 12) || 12),
            "%M": padTemporal(date.getMinutes()),
            "%S": padTemporal(date.getSeconds()),
            "%p": hour < 12 ? "AM" : "PM",
            "%x": date.toLocaleDateString(),
            "%X": date.toLocaleTimeString(),
            "%%": "%",
        };
        return String(format || "").replace(
            /%%|%[YymdHIMSpxX]/g, token => replacements[token] ?? token);
    }

    function temporalParse(input) {
        const value = input.value.trim();
        if (!value) {
            return null;
        }
        const format = input.dataset.temporalFormat || "";
        const tokens = [];
        const patterns = {
            Y: "(\\d{4})", y: "(\\d{2})", m: "(\\d{1,2})",
            d: "(\\d{1,2})", H: "(\\d{1,2})", I: "(\\d{1,2})",
            M: "(\\d{1,2})", S: "(\\d{1,2})", p: "(AM|PM|am|pm)",
        };
        let expression = "^";
        for (let index = 0; index < format.length; index += 1) {
            if (format[index] === "%" && index + 1 < format.length) {
                const token = format[index + 1];
                index += 1;
                if (token === "%") {
                    expression += "%";
                } else if (patterns[token]) {
                    expression += patterns[token];
                    tokens.push(token);
                } else {
                    expression += ".+?";
                }
            } else if (/\s/.test(format[index])) {
                expression += "\\s+";
            } else {
                expression += format[index].replace(
                    /[.*+?^${}()|[\]\\]/g, "\\$&");
            }
        }
        let match = value.match(new RegExp(expression + "$"));
        if (!match && /^\d+$/.test(value) && tokens.length) {
            const compactExpression = tokens.map(function (token, index) {
                const pattern = token === "Y" ? "(\\d{2,4})" :
                    token === "y" ? "(\\d{2})" : "(\\d{1,2})";
                return index ? pattern + "?" : pattern;
            }).join("");
            match = value.match(new RegExp("^" + compactExpression + "$"));
        }
        if (!match) {
            return null;
        }
        const now = new Date();
        const parts = {
            Y: now.getFullYear(), m: now.getMonth() + 1,
            d: now.getDate(), H: 0, M: 0, S: 0,
        };
        let meridiem = null;
        tokens.forEach((token, index) => {
            const raw = match[index + 1];
            if (raw === undefined) {
                return;
            }
            if (token === "p") {
                meridiem = raw.toUpperCase();
            } else if (token === "y" ||
                    (token === "Y" && raw.length === 2)) {
                const year = Number(raw);
                parts.Y = year + (year >= 69 ? 1900 : 2000);
            } else {
                parts[token] = Number(raw);
            }
        });
        if (tokens.includes("I")) {
            parts.H = parts.I % 12 + (meridiem === "PM" ? 12 : 0);
        }
        if (parts.m < 1 || parts.m > 12 || parts.d < 1 ||
                parts.H < 0 || parts.H > 23 || parts.M < 0 ||
                parts.M > 59 || parts.S < 0 || parts.S > 59) {
            return null;
        }
        const result = new Date(0);
        result.setHours(0, 0, 0, 0);
        result.setFullYear(parts.Y, parts.m - 1, parts.d);
        result.setHours(parts.H, parts.M, parts.S, 0);
        if (Number.isNaN(result.getTime()) ||
                result.getFullYear() !== parts.Y ||
                result.getMonth() !== parts.m - 1 ||
                result.getDate() !== parts.d) {
            return null;
        }
        return result;
    }

    function temporalISO(date, kind) {
        const datePart = [
            padTemporal(date.getFullYear(), 4),
            padTemporal(date.getMonth() + 1),
            padTemporal(date.getDate()),
        ].join("-");
        const timePart = [
            padTemporal(date.getHours()),
            padTemporal(date.getMinutes()),
            padTemporal(date.getSeconds()),
        ].join(":");
        if (kind === "date") {
            return datePart;
        }
        if (kind === "time") {
            return timePart;
        }
        return datePart + "T" + timePart;
    }

    function setTemporalValue(input, date) {
        input.value = temporalFormat(date, input.dataset.temporalFormat);
        input.dataset.temporalValue = temporalISO(
            date, input.dataset.temporalKind);
        const picker = input.closest("[data-temporal-widget]")
            ?.querySelector("[data-temporal-picker-input]");
        if (picker) {
            picker.value = input.dataset.temporalValue;
        }
    }

    function adjustTemporal(date, unit, amount) {
        const result = new Date(date.getTime());
        if (unit === "month" || unit === "year") {
            const day = result.getDate();
            result.setDate(1);
            if (unit === "month") {
                result.setMonth(result.getMonth() + amount);
            } else {
                result.setFullYear(result.getFullYear() + amount);
            }
            const lastDay = new Date(
                result.getFullYear(), result.getMonth() + 1, 0).getDate();
            result.setDate(Math.min(day, lastDay));
            return result;
        }
        const milliseconds = {
            second: 1000,
            minute: 60 * 1000,
            hour: 60 * 60 * 1000,
            day: 24 * 60 * 60 * 1000,
            week: 7 * 24 * 60 * 60 * 1000,
        }[unit];
        return new Date(result.getTime() + amount * milliseconds);
    }

    function prepareFocusedPreservation(event) {
        rememberFocus();
        const requestElement = event.detail?.requestConfig?.elt;
        if (requestElement?.matches("[data-chat-form]") &&
                focusState.id === "message") {
            focusState.value = "";
            focusState.start = 0;
            focusState.end = 0;
        }
        const active = document.activeElement;
        const response = event.detail && event.detail.serverResponse;
        if (!response) {
            return;
        }
        const template = document.createElement("template");
        template.innerHTML = response;
        let index = 0;
        for (const incoming of template.content.querySelectorAll(
                "[hx-preserve][id]")) {
            const element = document.getElementById(incoming.id);
            if (!element || element === active) {
                continue;
            }
            element.id = "vs-replaced-" + Date.now() + "-" + index;
            index += 1;
        }
    }

    function syncShellState() {
        const app = document.getElementById("cassini");
        if (!app) {
            return;
        }
        const theme = app.dataset.theme === "dark" ? "dark" : "light";
        document.documentElement.dataset.theme = theme;
        document.documentElement.classList.toggle("dark", theme === "dark");
        const sidebar = app.querySelector(".vs-sidebar[data-panel-kind]");
        if (sidebarResizeObserver && sidebar !== observedSidebar) {
            if (observedSidebar) {
                sidebarResizeObserver.unobserve(observedSidebar);
            }
            observedSidebar = sidebar;
            if (sidebar) {
                sidebarResizeObserver.observe(
                    sidebar, {box: "border-box"});
            }
        }
    }

    function captureSidebarWidth(persist) {
        const app = document.getElementById("cassini");
        const sidebar = app?.querySelector(
            ".vs-sidebar[data-panel-kind]");
        if (!sidebar || getComputedStyle(sidebar).resize !== "horizontal") {
            return;
        }
        const kind = sidebar.dataset.panelKind;
        if (kind !== "menu" && kind !== "help") {
            return;
        }
        const width = Math.round(sidebar.getBoundingClientRect().width);
        if (!Number.isFinite(width) || width < 192) {
            return;
        }
        const property = kind + "Width";
        const changed = Number(app.dataset[property]) !== width;
        app.dataset[property] = String(width);
        const input = app.querySelector(
            "[data-shell-panel-width='" + kind + "']");
        if (input) {
            input.value = String(width);
        }
        if (!persist || !changed || !app.dataset.panelWidthUrl) {
            return;
        }
        window.clearTimeout(sidebarWidthTimer);
        const url = app.dataset.panelWidthUrl;
        const menuWidth = app.dataset.menuWidth;
        const helpWidth = app.dataset.helpWidth;
        sidebarWidthTimer = window.setTimeout(function () {
            sidebarWidthTimer = null;
            const data = new FormData();
            data.set("menu_width", menuWidth);
            data.set("help_width", helpWidth);
            fetch(url, {
                method: "POST",
                body: data,
                credentials: "same-origin",
                headers: {"HX-Request": "true"},
            }).catch(function () {
                // The next panel action sends both widths again.
            });
        }, 250);
    }

    function syncWorkspaceStickyOffsets() {
        for (const workspace of document.querySelectorAll(".vs-workspace")) {
            const tabs = workspace.querySelector(":scope > .vs-tabs");
            if (!tabs) {
                workspace.style.removeProperty("--vs-tabs-height");
            } else {
                if (workspaceResizeObserver &&
                        !observedWorkspaceTabs.has(tabs)) {
                    observedWorkspaceTabs.add(tabs);
                    workspaceResizeObserver.observe(
                        tabs, {box: "border-box"});
                }
                workspace.style.setProperty(
                    "--vs-tabs-height",
                    tabs.getBoundingClientRect().height + "px");
            }
            for (const screen of workspace.querySelectorAll(".vs-screen")) {
                const toolbar = screen.querySelector(
                    ":scope > .vs-toolbar");
                if (!toolbar) {
                    screen.style.removeProperty(
                        "--vs-sticky-toolbar-height");
                    continue;
                }
                if (workspaceResizeObserver &&
                        !observedWorkspaceToolbars.has(toolbar)) {
                    observedWorkspaceToolbars.add(toolbar);
                    workspaceResizeObserver.observe(
                        toolbar, {box: "border-box"});
                }
                const toolbarBox = toolbar.getBoundingClientRect();
                let toolbarBottom = toolbarBox.bottom;
                for (const child of toolbar.children) {
                    if (getComputedStyle(child).display !== "none") {
                        toolbarBottom = Math.max(
                            toolbarBottom,
                            child.getBoundingClientRect().bottom);
                    }
                }
                screen.style.setProperty(
                    "--vs-sticky-toolbar-height",
                    Math.max(0, toolbarBottom - toolbarBox.top) + "px");
            }
        }
    }

    function scheduleWorkspaceStickyOffsets() {
        if (workspaceStickyFrame !== null) {
            return;
        }
        workspaceStickyFrame = window.requestAnimationFrame(function () {
            workspaceStickyFrame = null;
            syncWorkspaceStickyOffsets();
        });
    }

    function closeSearchCompletion(input) {
        const form = input?.closest(".vs-search-form");
        const completion = form?.querySelector(
            "[data-search-completion-list]");
        if (completion) {
            completion.hidden = true;
        }
        input?.setAttribute("aria-expanded", "false");
    }

    function updateSearchCompletion(input) {
        const form = input.closest(".vs-search-form");
        const completion = form?.querySelector(
            "[data-search-completion-list]");
        if (!completion) {
            return;
        }
        const query = input.value.trimStart().toLocaleLowerCase();
        const canComplete = Boolean(query);
        let visible = 0;
        for (const option of completion.querySelectorAll(
                "[data-search-completion-option]")) {
            const value = (
                option.dataset.searchCompletionOption || ""
            ).toLocaleLowerCase();
            option.hidden = !canComplete || !value.startsWith(query);
            if (!option.hidden) {
                visible += 1;
            }
        }
        completion.hidden = visible === 0;
        input.setAttribute("aria-expanded", String(visible > 0));
    }

    function initializeSearchCompletions() {
        for (const input of document.querySelectorAll(
                "[data-search-autocomplete]")) {
            if (input === document.activeElement) {
                updateSearchCompletion(input);
            } else {
                closeSearchCompletion(input);
            }
        }
    }

    function dismissPopupsOutside(target) {
        for (const container of document.querySelectorAll(
                "[data-dismissible-popup-container]")) {
            if (container.contains(target)) {
                continue;
            }
            const popup = container.querySelector(
                "[data-dismissible-popup]");
            if (!popup || (popup.dataset.dismissiblePopup === "empty" &&
                    !popup.hasChildNodes())) {
                continue;
            }
            if (popup.dataset.dismissiblePopup === "empty") {
                popup.replaceChildren();
            } else {
                popup.remove();
            }
            const trigger = container.querySelector("[aria-expanded]");
            trigger?.setAttribute("aria-expanded", "false");
            const synchronizer = container.querySelector(
                "[data-dismissible-popup-sync]");
            synchronizer?.click();
        }
    }

    let chatTimer = null;

    function scheduleChatPolling() {
        window.clearTimeout(chatTimer);
        const chat = document.querySelector("[data-chat-poll-url]");
        if (!chat || !chat.dataset.chatPollUrl) {
            return;
        }
        chatTimer = window.setTimeout(async function () {
            const current = document.querySelector("[data-chat-poll-url]");
            if (!current || !current.dataset.chatPollUrl) {
                return;
            }
            try {
                const response = await fetch(current.dataset.chatPollUrl, {
                    credentials: "same-origin",
                    headers: {"HX-Request": "true"},
                });
                if (response.ok) {
                    const template = document.createElement("template");
                    template.innerHTML = (await response.text()).trim();
                    const panel = document.getElementById("help-panel");
                    if (panel && template.content.firstElementChild) {
                        panel.replaceWith(template.content.firstElementChild);
                        initializeHelp();
                    }
                }
            } finally {
                scheduleChatPolling();
            }
        }, 2000);
    }

    function closeModal() {
        const nested = document.getElementById("relation-modal");
        if (nested && nested.childElementCount) {
            nested.replaceChildren();
            return;
        }
        const modal = document.getElementById("modal");
        if (modal) {
            const content = modal.querySelector("[data-close-url]");
            if (content) {
                fetch(content.dataset.closeUrl, {
                    method: "POST",
                    credentials: "same-origin",
                    headers: {"HX-Request": "true"},
                });
            }
            modal.replaceChildren();
        }
    }

    function cancelTopModal() {
        const backdrops = Array.from(document.querySelectorAll(
            ".vs-modal-backdrop")).filter(isVisible);
        const backdrop = backdrops.at(-1);
        const cancel = backdrop?.querySelector(
            "[data-modal-cancel], [data-close-relation-modal], " +
            "[data-close-modal]");
        if (cancel && !cancel.disabled) {
            cancel.click();
            return true;
        }
        if (backdrop) {
            closeModal();
            return true;
        }
        return false;
    }

    function showShortcutHelp() {
        const host = document.getElementById("modal");
        if (!host) {
            return false;
        }
        const backdrop = document.createElement("div");
        backdrop.className = "vs-modal-backdrop";
        const dialog = document.createElement("section");
        dialog.className = "vs-modal vs-shortcut-dialog";
        dialog.setAttribute("role", "dialog");
        dialog.setAttribute("aria-modal", "true");
        dialog.setAttribute("aria-labelledby", "shortcut-help-title");
        const title = document.createElement("h2");
        title.id = "shortcut-help-title";
        title.textContent = tr("Keyboard shortcuts");
        const columns = document.createElement("div");
        columns.className = "vs-shortcut-columns";
        for (const [scope, heading] of [
            ["global", tr("Global shortcuts")],
            ["tab", tr("Tab shortcuts")],
        ]) {
            const section = document.createElement("section");
            const subtitle = document.createElement("h3");
            subtitle.textContent = heading;
            const list = document.createElement("dl");
            list.className = "vs-shortcut-list";
            for (const definition of shortcutDefinitions.filter(
                    item => item.scope === scope)) {
                const term = document.createElement("dt");
                if (definition.action === "help" && hasAssistantPanel()) {
                    term.textContent = tr("Cycle side panel");
                } else if (definition.action === "global-search" &&
                        hasAssistantPanel()) {
                    term.textContent = tr(
                        "Global search or start a new assistant conversation");
                } else {
                    term.textContent = definition.label;
                }
                const description = document.createElement("dd");
                const key = document.createElement("kbd");
                key.textContent = definition.shortcut;
                description.append(key);
                list.append(term, description);
            }
            section.append(subtitle, list);
            columns.append(section);
        }
        const actions = document.createElement("div");
        actions.className = "vs-dialog-actions";
        const close = document.createElement("button");
        close.type = "button";
        close.className = "vs-button vs-button-primary";
        close.dataset.closeModal = "true";
        close.textContent = tr("Close");
        actions.append(close);
        dialog.append(title, columns, actions);
        backdrop.append(dialog);
        backdrop.addEventListener("click", function (event) {
            if (event.target === backdrop) {
                closeModal();
            }
        });
        host.replaceChildren(backdrop);
        close.focus();
        return true;
    }

    function hasAssistantPanel() {
        return Boolean(document.querySelector(
            "[data-panel-option='help']"));
    }

    function cycleShellPanel() {
        const app = document.getElementById("cassini");
        if (!app || !hasAssistantPanel()) {
            return false;
        }
        const states = ["none", "menu", "help"];
        const current = states.indexOf(app.dataset.panel);
        const next = states[current < 0 ? 0 : (current + 1) % states.length];
        const button = app.querySelector(
            `[data-panel-option="${next}"]`);
        if (!button || button.disabled) {
            return false;
        }
        captureSidebarWidth(false);
        window.clearTimeout(sidebarWidthTimer);
        sidebarWidthTimer = null;
        window.htmx.ajax("POST", button.getAttribute("hx-post"), {
            source: button,
            target: "#cassini",
            swap: "outerHTML",
        });
        return true;
    }

    function matchesShortcut(event, definition) {
        return event.key.toLowerCase() === definition.key &&
            event.ctrlKey === Boolean(definition.ctrl) &&
            event.altKey === Boolean(definition.alt) &&
            event.shiftKey === Boolean(definition.shift) &&
            !event.metaKey;
    }

    function moveWorkspaceTab(direction) {
        const tabs = Array.from(document.querySelectorAll(
            "#workspace-tabs .vs-tab"));
        if (tabs.length < 2) {
            return false;
        }
        const active = tabs.findIndex(tab =>
            tab.classList.contains("vs-tab-active"));
        const index = (
            active + direction + tabs.length
        ) % tabs.length;
        tabs[index].querySelector(".vs-tab-title")?.click();
        return true;
    }

    function activateShortcut(action) {
        if (action === "help") {
            return cycleShellPanel() || showShortcutHelp();
        }
        if (action === "accesskeys") {
            document.documentElement.classList.toggle("vs-accesskeys");
            return true;
        }
        if (action === "global-search") {
            const search = document.querySelector(
                "[data-global-search-input]");
            search?.focus({preventScroll: true});
            return Boolean(search);
        }
        if (action === "previous-tab" || action === "next-tab") {
            return moveWorkspaceTab(action === "previous-tab" ? -1 : 1);
        }
        if (action === "close") {
            const close = document.querySelector(
                "#workspace-tabs .vs-tab-active .vs-tab-close");
            close?.click();
            return Boolean(close);
        }
        const screen = document.querySelector(
            ".vs-active-panel > .vs-screen");
        if (!screen) {
            return false;
        }
        if (action === "search") {
            const search = screen.querySelector(".vs-search-input");
            if (search) {
                search.focus({preventScroll: true});
                return true;
            }
            const switchView = screen.querySelector(
                "[data-search-view-switch]");
            if (switchView) {
                focusSearchAfterSwap = true;
                switchView.click();
                return true;
            }
            return false;
        }
        const target = (
            screen.querySelector(
                `.vs-toolbar-actions ` +
                `[data-shortcut-action="${action}"]`) ||
            screen.querySelector(
                `[data-shortcut-action="${action}"]`));
        if (!target || target.disabled ||
                target.closest("[disabled]")) {
            return false;
        }
        target.click();
        return true;
    }

    function focusPendingSearch() {
        if (!focusSearchAfterSwap) {
            return;
        }
        const search = document.querySelector(
            ".vs-active-panel > .vs-screen .vs-search-input");
        if (search) {
            focusSearchAfterSwap = false;
            search.focus({preventScroll: true});
        }
    }

    function requestConfirmation(message) {
        return new Promise(function (resolve) {
            const host = document.createElement("div");
            host.className = "vs-confirm-host";
            const backdrop = document.createElement("div");
            backdrop.className = "vs-modal-backdrop";
            const dialog = document.createElement("section");
            dialog.className = "vs-modal vs-confirm-dialog";
            dialog.setAttribute("role", "alertdialog");
            dialog.setAttribute("aria-modal", "true");
            dialog.setAttribute("aria-labelledby", "vs-confirm-title");
            dialog.setAttribute(
                "aria-describedby", "vs-confirm-description");
            const heading = document.createElement("div");
            heading.className = "vs-confirm-heading";
            const icon = document.createElement("span");
            icon.className = "vs-confirm-symbol";
            icon.setAttribute("aria-hidden", "true");
            icon.textContent = "!";
            const title = document.createElement("h2");
            title.id = "vs-confirm-title";
            title.textContent = tr("Confirm action");
            heading.append(icon, title);
            const description = document.createElement("p");
            description.id = "vs-confirm-description";
            description.textContent = message;
            const actions = document.createElement("div");
            actions.className = "vs-dialog-actions";
            const cancel = document.createElement("button");
            cancel.type = "button";
            cancel.className = "vs-button";
            cancel.textContent = tr("Cancel");
            const accept = document.createElement("button");
            accept.type = "button";
            accept.className = "vs-button vs-button-primary";
            accept.textContent = tr("Continue");
            actions.append(cancel, accept);
            dialog.append(heading, description, actions);
            backdrop.append(dialog);
            host.append(backdrop);
            document.body.append(host);

            let completed = false;
            const finish = function (accepted) {
                if (completed) {
                    return;
                }
                completed = true;
                host.remove();
                resolve(accepted);
            };
            cancel.addEventListener("click", () => finish(false));
            accept.addEventListener("click", () => finish(true));
            backdrop.addEventListener("click", function (event) {
                if (event.target === backdrop) {
                    finish(false);
                }
            });
            dialog.addEventListener("keydown", function (event) {
                if (event.key === "Escape") {
                    event.preventDefault();
                    finish(false);
                }
            });
            cancel.focus();
        });
    }

    function loadExternalScript(source) {
        const existing = document.querySelector(
            "script[src=\"" + CSS.escape(source) + "\"]");
        if (existing?.dataset.loaded === "true") {
            return Promise.resolve();
        }
        return new Promise(function (resolve, reject) {
            const script = existing || document.createElement("script");
            script.addEventListener("load", function () {
                script.dataset.loaded = "true";
                resolve();
            }, {once: true});
            script.addEventListener("error", function () {
                reject(new Error(tr("The requested JavaScript library could not be loaded.")));
            }, {once: true});
            if (!existing) {
                script.src = source;
                document.head.append(script);
            }
        });
    }

    function decodeBase64Text(value) {
        let encoded = String(value || "")
            .replaceAll("-", "+").replaceAll("_", "/");
        encoded += "=".repeat((4 - encoded.length % 4) % 4);
        const binary = window.atob(encoded);
        const bytes = Uint8Array.from(binary, character =>
            character.charCodeAt(0));
        return new TextDecoder("utf-8").decode(bytes);
    }

    function loadPlotly() {
        if (window.Plotly?.newPlot) {
            return Promise.resolve(window.Plotly);
        }
        if (!plotlyPromise) {
            plotlyPromise = loadExternalScript(
                "https://cdn.plot.ly/plotly-3.6.0.min.js")
                .then(function () {
                    if (!window.Plotly?.newPlot) {
                        throw new Error(tr("Plotly could not be initialized."));
                    }
                    return window.Plotly;
                });
        }
        return plotlyPromise;
    }

    function initializeCharts(root=document) {
        for (const node of root.querySelectorAll(
                "[data-cassini-chart]:not([data-chart-initialized])")) {
            node.dataset.chartInitialized = "true";
            let chart;
            try {
                chart = JSON.parse(decodeBase64Text(
                    node.dataset.chartPayload));
            } catch (error) {
                node.textContent = tr("The chart data is not valid.");
                node.classList.add("vs-chart-error");
                continue;
            }
            if (!chart?.data?.length) {
                continue;
            }
            const information = chart.data[0] || {};
            if (information.type === "value") {
                const value = document.createElement("strong");
                value.className = "vs-chart-value";
                value.textContent = information.value ?? "";
                node.replaceChildren(value);
                continue;
            }
            if (information.type === "error") {
                const error = document.createElement("p");
                error.className = "vs-chart-error";
                error.textContent = information.message || "";
                node.replaceChildren(error);
                continue;
            }
            loadPlotly().then(function (Plotly) {
                if (!node.isConnected) {
                    return;
                }
                const layout = Object.assign({}, chart.layout || {}, {
                    autosize: true,
                    separators: ",.",
                    margin: Object.assign({
                        t: 40, l: 40, r: 40, b: 40,
                    }, chart.layout?.margin || {}),
                });
                const config = Object.assign({}, chart.config || {}, {
                    responsive: true,
                });
                return Plotly.newPlot(node, chart.data, layout, config);
            }).catch(function (error) {
                node.textContent = error.message;
                node.classList.add("vs-chart-error");
            });
        }
    }

    function loadMonaco() {
        if (window.CassiniMonaco?.editor) {
            return Promise.resolve(window.CassiniMonaco);
        }
        if (!document.querySelector("link[data-monaco-icons]")) {
            const stylesheet = document.createElement("link");
            stylesheet.rel = "stylesheet";
            stylesheet.href = "https://cdn.jsdelivr.net/npm/" +
                "vscode-codicons@0.0.17/dist/codicon.min.css";
            stylesheet.dataset.monacoIcons = "true";
            document.head.append(stylesheet);
        }
        if (!monacoPromise) {
            monacoPromise = import(
                "https://cdn.jsdelivr.net/npm/monaco-editor-core@0.55.1/+esm");
        }
        return monacoPromise;
    }

    function initializeCodeEditors(root=document) {
        for (const widget of root.querySelectorAll(
                "[data-code-widget]:not([data-code-initialized])")) {
            widget.dataset.codeInitialized = "true";
            const source = widget.querySelector("[data-code-source]");
            const host = widget.querySelector("[data-code-editor]");
            if (!source || !host) {
                continue;
            }
            loadMonaco().then(function (monaco) {
                if (!widget.isConnected) {
                    return;
                }
                let synchronizing = false;
                const editor = monaco.editor.create(host, {
                    value: source.value || "",
                    language: widget.dataset.codeLanguage || "plaintext",
                    theme: "vs-dark",
                    readOnly: widget.dataset.codeReadonly === "true",
                    automaticLayout: true,
                });
                widget._cassiniEditor = editor;
                source.classList.add("vs-code-source-ready");
                editor.getModel().onDidChangeContent(function () {
                    if (synchronizing) {
                        return;
                    }
                    source.value = editor.getValue();
                    source.dispatchEvent(new Event("input", {bubbles: true}));
                });
                editor.onDidBlurEditorText(function () {
                    if (source.value !== (
                            source.dataset.serverValue ?? source.defaultValue)) {
                        source.dispatchEvent(new Event(
                            "change", {bubbles: true}));
                    }
                });
                if (monaco.KeyMod && monaco.KeyCode) {
                    editor.addCommand(
                        monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS,
                        function () {
                            source.dispatchEvent(new Event(
                                "change", {bubbles: true}));
                            window.setTimeout(function () {
                                document.querySelector(
                                    "[data-shortcut-action='save']" +
                                    ":not([disabled])")?.click();
                            }, 0);
                        });
                }
                synchronizing = true;
                editor.setValue(source.value || "");
                synchronizing = false;
            }).catch(function (error) {
                widget.dataset.codeInitialized = "error";
                host.textContent = error.message;
                host.classList.add("vs-code-error");
            });
        }
    }

    function initializeDynamicWidgets(root=document) {
        initializeCharts(root);
        initializeCodeEditors(root);
    }

    function cassiniDatabasePrefix() {
        const database = window.location.pathname.split("/")
            .filter(Boolean)[0] || "";
        return "/" + database;
    }

    function configureQZ(qz) {
        if (!qzConfigured) {
            qz.security.setCertificatePromise(
                function (resolve, reject) {
                    fetch("/cassini-qz/certificate.txt", {
                        cache: "no-store",
                    }).then(function (response) {
                        if (!response.ok) {
                            throw new Error(response.statusText);
                        }
                        return response.text();
                    }).then(resolve, reject);
                });
            qz.security.setSignatureAlgorithm("SHA512");
            qz.security.setSignaturePromise(function (toSign) {
                return function (resolve, reject) {
                    fetch(cassiniDatabasePrefix() +
                            "/printer/sign_message", {
                        method: "POST",
                        cache: "no-cache",
                        credentials: "same-origin",
                        headers: {"Content-Type": "application/json"},
                        body: JSON.stringify({request: toSign}),
                    }).then(function (response) {
                        if (!response.ok) {
                            throw new Error(response.statusText);
                        }
                        return response.text();
                    }).then(resolve, reject);
                };
            });
            qzConfigured = true;
        }
        return qz;
    }

    function loadQZ() {
        if (window.qz?.print) {
            return Promise.resolve(configureQZ(window.qz));
        }
        if (!qzPromise) {
            qzPromise = loadExternalScript("/cassini-qz/qz-tray.js")
                .then(function () {
                    const qz = window.qz;
                    if (!qz?.print) {
                        throw new Error(tr("QZ Tray could not be initialized."));
                    }
                    return configureQZ(qz);
                });
        }
        return qzPromise;
    }

    function blobToBase64(blob) {
        return new Promise(function (resolve, reject) {
            const reader = new FileReader();
            reader.addEventListener("load", function () {
                resolve(String(reader.result).split(",").pop());
            }, {once: true});
            reader.addEventListener("error", reject, {once: true});
            reader.readAsDataURL(blob);
        });
    }

    async function printWithQZ(blob, reportType, printerName) {
        const qz = await loadQZ();
        const connected = qz.websocket.isActive();
        if (!connected) {
            await qz.websocket.connect();
        }
        try {
            const printer = await qz.printers.find(printerName);
            const configuration = qz.configs.create(printer);
            let data;
            if (reportType === "pdf") {
                data = [{
                    type: "pixel", format: "pdf", flavor: "base64",
                    data: await blobToBase64(blob),
                }];
            } else if (["png", "jpg", "jpeg", "gif", "svg", "webp"]
                    .includes(reportType.toLowerCase())) {
                data = [{
                    type: "pixel", format: "image", flavor: "base64",
                    data: await blobToBase64(blob),
                }];
            } else {
                const buffer = new Uint8Array(await blob.arrayBuffer());
                let text = "";
                for (let offset = 0; offset < buffer.length; offset += 8192) {
                    text += String.fromCharCode(...buffer.slice(
                        offset, offset + 8192));
                }
                if (["zpl", "epl", "tec", "TECSV4_B", "TECFV4_B",
                        "ZEBRA_B"].includes(reportType)) {
                    data = [{
                        type: "raw", format: "command", flavor: "plain",
                        data: text,
                    }];
                } else {
                    data = [{
                        type: "pixel", format: "html", flavor: "plain",
                        data: new TextDecoder("utf-8").decode(buffer),
                    }];
                }
            }
            await qz.print(configuration, data);
        } finally {
            if (!connected && qz.websocket.isActive()) {
                await qz.websocket.disconnect();
            }
        }
    }

    function responseFilename(response, fallback) {
        const disposition = response.headers.get("Content-Disposition") || "";
        const encoded = disposition.match(/filename\*=UTF-8''([^;]+)/i);
        if (encoded) {
            return decodeURIComponent(encoded[1]);
        }
        const plain = disposition.match(/filename="([^"]+)"/i);
        return plain ? plain[1] : fallback;
    }

    function downloadBlob(blob, filename) {
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = filename;
        link.hidden = true;
        document.body.append(link);
        link.click();
        link.remove();
        window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    }

    async function downloadOrPrint(url) {
        const response = await fetch(url, {credentials: "same-origin"});
        if (!response.ok) {
            throw new Error(await response.text());
        }
        const reportType = response.headers.get(
            "X-Cassini-Report-Type") || "bin";
        const filename = responseFilename(
            response, "report." + reportType);
        const blob = await response.blob();
        if (response.headers.get("X-Cassini-Direct-Print") !== "true") {
            downloadBlob(blob, filename);
            return;
        }
        let printerName = "";
        try {
            printerName = decodeBase64Text(
                response.headers.get("X-Cassini-Printer") || "");
        } catch (error) {
            printerName = filename.replace(/\.[^.]+$/, "");
        }
        try {
            await printWithQZ(blob, reportType, printerName);
        } catch (error) {
            showClientNotice(tr("Direct printing failed: %(error)s", {
                error: error.message,
            }), true);
            downloadBlob(blob, filename);
        }
    }

    function startDownloads(detail) {
        const urls = detail && detail.urls ? detail.urls : [];
        for (const url of urls) {
            qzPrintQueue = qzPrintQueue
                .catch(() => undefined)
                .then(() => downloadOrPrint(url))
                .catch(error => showClientNotice(error.message, true));
        }
    }

    function openURLs(detail) {
        const urls = detail && detail.urls ? detail.urls : [];
        for (const url of urls) {
            window.open(url, "_blank", "noreferrer,noopener");
        }
    }

    async function shareTab(button) {
        const url = new URL(
            button.dataset.shareUrl || window.location.href,
            window.location.href).href;
        const data = {
            title: button.dataset.shareTitle || document.title,
            url: url,
        };
        if (navigator.share) {
            try {
                await navigator.share(data);
                return;
            } catch (error) {
                if (error.name === "AbortError") {
                    return;
                }
            }
        }
        if (navigator.clipboard?.writeText) {
            await navigator.clipboard.writeText(url);
            return;
        }
        const input = document.createElement("textarea");
        input.value = url;
        input.style.position = "fixed";
        input.style.opacity = "0";
        document.body.append(input);
        input.select();
        document.execCommand("copy");
        input.remove();
    }

    function scheduleNoticeDismissal() {
        const host = document.getElementById("notifications");
        const notice = host && host.lastElementChild;
        if (!notice) {
            return;
        }
        window.setTimeout(function () {
            if (notice.parentElement === host) {
                notice.remove();
            }
        }, 8000);
    }

    function showClientNotice(message, error) {
        const host = document.getElementById("notifications");
        if (!host) {
            return;
        }
        const notice = document.createElement("div");
        notice.className = "vs-notice" +
            (error ? " vs-notice-error" : "");
        notice.textContent = message;
        host.replaceChildren(notice);
        scheduleNoticeDismissal();
    }

    function renderChatMarkdown(panel) {
        for (const node of panel.querySelectorAll(
                "[data-chat-markdown]:not([data-markdown-rendered])")) {
            node.dataset.markdownRendered = "true";
            if (!window.showdown ||
                    typeof window.showdown.Converter !== "function") {
                continue;
            }
            const converter = new window.showdown.Converter({
                tables: true,
                strikethrough: true,
                tasklists: true,
                simplifiedAutoLink: true,
                openLinksInNewWindow: true,
            });
            const template = document.createElement("template");
            template.innerHTML = converter.makeHtml(node.textContent || "");
            template.content.querySelectorAll(
                "script, iframe, object, embed, form").forEach(
                element => element.remove());
            for (const element of template.content.querySelectorAll("*")) {
                for (const attribute of Array.from(element.attributes)) {
                    const name = attribute.name.toLowerCase();
                    const value = attribute.value.trim().toLowerCase();
                    if (name.startsWith("on") ||
                            ((name === "href" || name === "src") &&
                             value.startsWith("javascript:"))) {
                        element.removeAttribute(attribute.name);
                    }
                }
            }
            node.replaceChildren(template.content);
        }
    }

    function openCobrowsingPopup() {
        const host = document.getElementById("modal");
        if (!host) {
            return;
        }
        const backdrop = document.createElement("div");
        backdrop.className = "vs-modal-backdrop";
        const dialog = document.createElement("section");
        dialog.className = "vs-modal vs-cobrowsing-modal";
        dialog.setAttribute("role", "dialog");
        dialog.setAttribute("aria-modal", "true");
        dialog.setAttribute("aria-labelledby", "cobrowsing-title");
        const title = document.createElement("h2");
        title.id = "cobrowsing-title";
        title.textContent = tr("Support");
        const message = document.createElement("p");
        message.textContent = tr(
            "Start a support session by sharing the current browser tab.");
        const actions = document.createElement("div");
        actions.className = "vs-dialog-actions vs-cobrowsing-actions";
        const cancel = document.createElement("button");
        cancel.type = "button";
        cancel.className = "vs-button";
        cancel.dataset.closeModal = "true";
        cancel.textContent = tr("Cancel");
        const accept = document.createElement("button");
        accept.type = "button";
        accept.className = "vs-button vs-button-primary";
        accept.dataset.startCobrowse = "true";
        accept.textContent = tr("OK");
        actions.append(cancel, accept);
        dialog.append(title, message, actions);
        backdrop.append(dialog);
        host.replaceChildren(backdrop);
        cancel.focus();
    }

    function initializeSurfly() {
        if (window.Surfly &&
                typeof window.Surfly.session === "function") {
            return Promise.resolve(window.Surfly);
        }
        if (surflyPromise) {
            return surflyPromise;
        }
        surflyPromise = new Promise(function (resolve, reject) {
            const initialize = function () {
                if (!window.Surfly ||
                        typeof window.Surfly.init !== "function") {
                    reject(new Error(tr(
                        "Remote assistance did not load.")));
                    return;
                }
                window.Surfly.init({
                    widget_key: "1030e18fa0f34d1f87fbdcdefb7ee4fd",
                    private_session: true,
                    require_password: false,
                    key_combo_to_start: false,
                }, function (result) {
                    if (result && result.success) {
                        resolve(window.Surfly);
                    } else {
                        reject(new Error(tr(
                            "Remote assistance could not be initialized.")));
                    }
                });
            };
            const existing = document.querySelector(
                "script[data-cassini-surfly]");
            if (existing) {
                existing.addEventListener("load", initialize, {once: true});
                existing.addEventListener(
                    "error",
                    () => reject(new Error(tr(
                        "Remote assistance did not load."))),
                    {once: true});
                return;
            }
            const script = document.createElement("script");
            script.src = "https://surfly.com/surfly.js";
            script.async = true;
            script.dataset.cassiniSurfly = "true";
            script.addEventListener("load", initialize, {once: true});
            script.addEventListener(
                "error",
                () => reject(new Error(tr(
                    "Remote assistance did not load."))),
                {once: true});
            document.head.append(script);
        }).catch(function (error) {
            surflyPromise = null;
            throw error;
        });
        return surflyPromise;
    }

    function chatFileInput(button) {
        return button.closest("[data-chat-form]")?.querySelector(
            "[data-chat-files]");
    }

    function addChatFiles(input, files) {
        if (!input || !files?.length) {
            return;
        }
        const transfer = new DataTransfer();
        for (const file of Array.from(input.files || [])) {
            transfer.items.add(file);
        }
        for (const file of Array.from(files)) {
            if (transfer.files.length >= 5) {
            showClientNotice(tr(
                "A maximum of five attachments is allowed."), true);
                break;
            }
            transfer.items.add(file);
        }
        input.files = transfer.files;
        renderChatFiles(input);
    }

    function renderChatFiles(input) {
        const container = input.closest("[data-chat-form]")?.querySelector(
            "[data-uploaded-files]");
        if (!container) {
            return;
        }
        container.replaceChildren();
        Array.from(input.files || []).forEach(function (file, index) {
            const item = document.createElement("span");
            item.className = "vs-uploaded-file";
            item.append(document.createTextNode(file.name));
            const remove = document.createElement("button");
            remove.type = "button";
            remove.dataset.removeChatFile = String(index);
            remove.setAttribute("aria-label", tr(
                "Remove %(file)s", {file: file.name}));
            remove.textContent = "×";
            item.append(remove);
            container.append(item);
        });
    }

    function removeChatFile(button) {
        const input = chatFileInput(button);
        if (!input) {
            return;
        }
        const removed = Number(button.dataset.removeChatFile);
        const transfer = new DataTransfer();
        Array.from(input.files || []).forEach(function (file, index) {
            if (index !== removed) {
                transfer.items.add(file);
            }
        });
        input.files = transfer.files;
        renderChatFiles(input);
    }

    async function captureScreenshot(button) {
        if (!navigator.mediaDevices?.getDisplayMedia) {
            showClientNotice(tr(
                "Screen capture is not available."), true);
            return;
        }
        let stream;
        try {
            stream = await navigator.mediaDevices.getDisplayMedia({
                video: true,
            });
            const video = document.createElement("video");
            video.srcObject = stream;
            await video.play();
            const canvas = document.createElement("canvas");
            canvas.width = video.videoWidth;
            canvas.height = video.videoHeight;
            canvas.getContext("2d").drawImage(video, 0, 0);
            const blob = await new Promise(resolve => {
                canvas.toBlob(resolve, "image/png");
            });
            if (blob) {
                addChatFiles(chatFileInput(button), [
                    new File(
                        [blob], "screenshot-" + Date.now() + ".png",
                        {type: "image/png"}),
                ]);
            }
        } catch (error) {
            if (error.name !== "NotAllowedError") {
                showClientNotice(tr(
                    "The screenshot could not be captured."), true);
            }
        } finally {
            stream?.getTracks().forEach(track => track.stop());
        }
    }

    async function toggleScreenRecording(button) {
        const active = chatRecorders.get(button);
        if (active) {
            active.recorder.stop();
            return;
        }
        if (!navigator.mediaDevices?.getDisplayMedia ||
                !window.MediaRecorder) {
            showClientNotice(tr(
                "Screen recording is not available."), true);
            return;
        }
        try {
            const stream = await navigator.mediaDevices.getDisplayMedia({
                video: true,
                audio: true,
            });
            const chunks = [];
            const recorder = new MediaRecorder(stream);
            chatRecorders.set(button, {recorder, stream});
            button.classList.add("vs-recording");
            recorder.addEventListener("dataavailable", event => {
                if (event.data.size) {
                    chunks.push(event.data);
                }
            });
            recorder.addEventListener("stop", function () {
                stream.getTracks().forEach(track => track.stop());
                chatRecorders.delete(button);
                button.classList.remove("vs-recording");
                if (chunks.length) {
                    const blob = new Blob(chunks, {
                        type: recorder.mimeType || "video/webm",
                    });
                    addChatFiles(chatFileInput(button), [
                        new File(
                            [blob], "recording-" + Date.now() + ".webm",
                            {type: blob.type}),
                    ]);
                }
            }, {once: true});
            stream.getVideoTracks()[0]?.addEventListener(
                "ended", () => {
                    if (recorder.state !== "inactive") {
                        recorder.stop();
                    }
                });
            recorder.start();
        } catch (error) {
            if (error.name !== "NotAllowedError") {
                showClientNotice(tr(
                    "The recording could not be started."), true);
            }
        }
    }

    async function toggleVoiceRecording(button) {
        const active = voiceRecorders.get(button);
        if (active) {
            active.recorder.stop();
            return;
        }
        if (!navigator.mediaDevices?.getUserMedia ||
                !window.MediaRecorder) {
            showClientNotice(tr(
                "Speech recognition is not available."), true);
            return;
        }
        try {
            const stream = await navigator.mediaDevices.getUserMedia({
                audio: true,
            });
            const chunks = [];
            const recorder = new MediaRecorder(stream);
            voiceRecorders.set(button, {recorder, stream});
            button.classList.add("vs-recording");
            recorder.addEventListener("dataavailable", event => {
                if (event.data.size) {
                    chunks.push(event.data);
                }
            });
            recorder.addEventListener("stop", async function () {
                stream.getTracks().forEach(track => track.stop());
                voiceRecorders.delete(button);
                button.classList.remove("vs-recording");
                if (!chunks.length) {
                    return;
                }
                const panel = button.closest("#help-panel");
                const input = panel?.querySelector("#message");
                const url = panel?.dataset.transcribeUrl;
                if (!input || !url) {
                    return;
                }
                const data = new FormData();
                data.append("audio", new Blob(chunks, {
                    type: recorder.mimeType || "audio/webm",
                }), "voice.webm");
                try {
                    const response = await fetch(url, {
                        method: "POST",
                        credentials: "same-origin",
                        body: data,
                    });
                    if (!response.ok) {
                        throw new Error(await response.text());
                    }
                    const result = await response.json();
                    input.value = [
                        input.value.trim(), result.text || "",
                    ].filter(Boolean).join(" ");
                    input.focus();
                } catch (error) {
                    showClientNotice(tr(
                        "The audio could not be transcribed."), true);
                }
            }, {once: true});
            recorder.start();
        } catch (error) {
            if (error.name !== "NotAllowedError") {
                showClientNotice(tr(
                    "The microphone could not be started."), true);
            }
        }
    }

    async function speakAssistant(panel, force) {
        if (!panel || (!speechEnabled && !force)) {
            return;
        }
        const messages = panel.querySelectorAll(
            ".vs-chat-assistant [data-chat-markdown]");
        const text = messages.length ?
            messages[messages.length - 1].textContent.trim() : "";
        if (!text || (!force && text === lastSpokenText)) {
            return;
        }
        try {
            const data = new FormData();
            data.set("text", text);
            const response = await fetch(panel.dataset.speechUrl, {
                method: "POST",
                credentials: "same-origin",
                body: data,
            });
            if (!response.ok) {
                throw new Error(await response.text());
            }
            const audio = new Audio(URL.createObjectURL(
                await response.blob()));
            audio.addEventListener("ended", function () {
                URL.revokeObjectURL(audio.src);
            }, {once: true});
            await audio.play();
            lastSpokenText = text;
        } catch (error) {
            speechEnabled = false;
            panel.querySelector("[data-help-speech]")?.classList.remove(
                "vs-recording");
            showClientNotice(tr(
                "The assistant voice is not available."), true);
        }
    }

    function initializeHelp() {
        const panel = document.getElementById("help-panel");
        if (!panel) {
            return;
        }
        renderChatMarkdown(panel);
        const output = panel.querySelector(".vs-chat-messages");
        if (output) {
            output.scrollTop = output.scrollHeight;
        }
        const speech = panel.querySelector("[data-help-speech]");
        speech?.classList.toggle("vs-recording", speechEnabled);
        if (speechEnabled) {
            speakAssistant(panel, false);
        }
        panel.querySelector("#message")?.focus({preventScroll: true});
    }

    function treeRowFromEvent(event, allowFieldControls) {
        if (event.target.closest(
                ".vs-select-column, .vs-drag-column, " +
                "button, a, summary, details") ||
                (!allowFieldControls && event.target.closest(
                    "input, select, textarea, label, " +
                    "[contenteditable='true']"))) {
            return null;
        }
        return event.target.closest(".vs-row");
    }

    function markTreeRowSelected(row, event, multiple) {
        const tree = row.closest(".vs-table-wrap");
        if (!tree) {
            return null;
        }
        const table = row.closest("table");
        const rows = Array.from(table?.tBodies[0]?.rows || []).filter(
            candidate => candidate.matches(".vs-row"));
        let current = rows.find(
            candidate => candidate.classList.contains("vs-row-current"));
        let selected = new Set(rows.filter(candidate => {
            const checkbox = candidate.querySelector(
                "td.vs-select-column input[name='selected']");
            return checkbox?.checked;
        }));
        if (multiple && event.shiftKey) {
            current = current || rows[0];
            const start = rows.indexOf(current);
            const end = rows.indexOf(row);
            const first = Math.min(start, end);
            const last = Math.max(start, end);
            selected = new Set(rows.slice(first, last + 1));
        } else if (multiple && (event.ctrlKey || event.metaKey)) {
            if (selected.has(row)) {
                selected.delete(row);
                current = rows.find(candidate => selected.has(candidate));
            } else {
                selected.add(row);
                current = row;
            }
        } else {
            selected = new Set([row]);
            current = row;
        }
        for (const candidate of rows) {
            const isSelected = selected.has(candidate);
            candidate.classList.toggle("vs-row-selected", isSelected);
            candidate.classList.toggle("vs-row-current", candidate === current);
            const checkbox = candidate.querySelector(
                "td.vs-select-column input[name='selected']");
            if (checkbox) {
                checkbox.checked = isSelected;
            }
        }
        const selectAll = tree.querySelector(
            "thead .vs-select-column input[name='selected']");
        if (selectAll) {
            selectAll.checked = Boolean(rows.length) &&
                selected.size === rows.length;
            selectAll.indeterminate = Boolean(selected.size) &&
                selected.size < rows.length;
        }
        return {
            records: rows.filter(candidate => selected.has(candidate)).map(
                candidate => candidate.dataset.record),
            current: current?.dataset.record || "",
        };
    }

    let treeDragState = null;

    function clearTreeDropState() {
        if (!treeDragState) {
            return;
        }
        treeDragState.tree.querySelectorAll(
            ".vs-row-drop-before, .vs-row-drop-after, " +
            ".vs-row-drop-inside").forEach(row => row.classList.remove(
                "vs-row-drop-before", "vs-row-drop-after",
                "vs-row-drop-inside"));
        treeDragState.row.classList.remove("vs-row-dragging");
        treeDragState = null;
    }

    document.addEventListener("dragstart", function (event) {
        const handle = event.target.closest?.("[data-tree-drag-handle]");
        const row = handle?.closest(".vs-row");
        const tree = row?.closest("[data-tree-reorder]");
        if (!handle || !row || !tree || !event.dataTransfer) {
            return;
        }
        treeDragState = {tree: tree, row: row, target: null, position: null};
        row.classList.add("vs-row-dragging");
        event.dataTransfer.effectAllowed = "move";
        event.dataTransfer.setData("text/plain", row.dataset.record || "");
        event.dataTransfer.setDragImage(row, 8, 8);
    });

    document.addEventListener("dragover", function (event) {
        if (!treeDragState) {
            return;
        }
        const target = event.target.closest?.(".vs-row");
        if (!target || target === treeDragState.row ||
                target.closest("[data-tree-reorder]") !== treeDragState.tree) {
            return;
        }
        event.preventDefault();
        event.dataTransfer.dropEffect = "move";
        treeDragState.tree.querySelectorAll(
            ".vs-row-drop-before, .vs-row-drop-after, " +
            ".vs-row-drop-inside").forEach(row => row.classList.remove(
                "vs-row-drop-before", "vs-row-drop-after",
                "vs-row-drop-inside"));
        const rectangle = target.getBoundingClientRect();
        const position = (
            treeDragState.tree.dataset.treeChildren === "true" &&
            (event.ctrlKey || event.metaKey))
            ? "inside"
            : event.clientY < rectangle.top + rectangle.height / 2
                ? "before" : "after";
        target.classList.add("vs-row-drop-" + position);
        treeDragState.target = target;
        treeDragState.position = position;
    });

    document.addEventListener("drop", function (event) {
        if (!treeDragState?.target) {
            return;
        }
        event.preventDefault();
        const state = treeDragState;
        const action = state.tree.querySelector("[data-tree-move-action]");
        const source = state.row.dataset.record;
        const target = state.target.dataset.record;
        const position = state.position;
        clearTreeDropState();
        if (!action || !source || !target || !position) {
            return;
        }
        const values = {target: target, position: position};
        values[
            action.dataset.treeMoveKind === "relation" ? "item" : "record"
        ] = source;
        action.setAttribute("hx-vals", JSON.stringify(values));
        action.click();
    });

    document.addEventListener("dragend", clearTreeDropState);

    function addCSVSelectedField(list, field, label) {
        if (!list || !field || Array.from(list.children).some(
                item => item.dataset.csvSelectedField === field)) {
            return;
        }
        const item = document.createElement("li");
        item.className = "vs-csv-selected-field";
        item.draggable = true;
        item.dataset.csvSelectedField = field;
        const handle = document.createElement("span");
        handle.className = "vs-csv-drag-handle";
        handle.textContent = "⋮⋮";
        handle.setAttribute("aria-hidden", "true");
        const text = document.createElement("span");
        text.textContent = label || field;
        const input = document.createElement("input");
        input.type = "hidden";
        input.name = "fields";
        input.value = field;
        item.append(handle, text, input);
        list.append(item);
    }

    function applyCSVExportProfile(button) {
        const form = button.closest("[data-csv-dialog='export']");
        const list = form?.querySelector("[data-csv-selected-list]");
        if (!form || !list) {
            return;
        }
        let profile;
        try {
            profile = JSON.parse(button.dataset.csvProfile || "{}");
        } catch (error) {
            return;
        }
        form.querySelectorAll("[data-csv-profile]").forEach(candidate => {
            candidate.classList.toggle("vs-selected", candidate === button);
        });
        list.replaceChildren();
        (profile.fields || []).forEach(field => {
            addCSVSelectedField(list, field.name, field.label);
        });
        const id = form.querySelector("[name='profile_id']");
        const name = form.querySelector("[name='export_name']");
        const records = form.querySelector("[name='records']");
        const header = form.querySelector("[name='header']");
        const ignore = form.querySelector("[name='ignore_search_limit']");
        if (id) {
            id.value = profile.id || "";
        }
        if (name) {
            name.value = profile.name || "";
        }
        if (records) {
            records.value = profile.records || "selected";
        }
        if (header) {
            header.checked = Boolean(profile.header);
        }
        if (ignore) {
            ignore.checked = Boolean(profile.ignore_search_limit);
        }
    }

    document.addEventListener("click", function (event) {
        const expand = event.target.closest?.("[data-csv-expand]");
        if (expand) {
            const target = expand.getAttribute("hx-target");
            const host = target ? document.querySelector(target) :
                expand.closest(".vs-csv-field")?.querySelector(
                    ":scope > .vs-csv-field-children");
            if (host) {
                host.hidden = !host.hidden;
                expand.classList.toggle("vs-expanded", !host.hidden);
            }
            return;
        }
        const choice = event.target.closest?.("[data-csv-field-choice]");
        if (choice) {
            const allFields = choice.closest(".vs-csv-all-fields");
            if (!(event.ctrlKey || event.metaKey)) {
                allFields?.querySelectorAll(
                    "[data-csv-field-choice].vs-selected").forEach(
                    selected => selected.classList.remove("vs-selected"));
            }
            choice.classList.toggle("vs-selected");
            return;
        }
        const add = event.target.closest?.("[data-csv-add]");
        if (add) {
            const form = add.closest("[data-csv-dialog]");
            const list = form?.querySelector("[data-csv-selected-list]");
            form?.querySelectorAll(
                "[data-csv-field-choice].vs-selected").forEach(choice => {
                addCSVSelectedField(
                    list, choice.dataset.csvField,
                    choice.dataset.csvLabel || choice.textContent.trim());
                choice.classList.remove("vs-selected");
            });
            return;
        }
        const selected = event.target.closest?.(
            "[data-csv-selected-field]");
        if (selected) {
            const list = selected.closest("[data-csv-selected-list]");
            if (!(event.ctrlKey || event.metaKey)) {
                list?.querySelectorAll(
                    "[data-csv-selected-field].vs-selected").forEach(
                    item => item.classList.remove("vs-selected"));
            }
            selected.classList.toggle("vs-selected");
            return;
        }
        const remove = event.target.closest?.("[data-csv-remove]");
        if (remove) {
            remove.closest("[data-csv-dialog]")?.querySelectorAll(
                "[data-csv-selected-field].vs-selected").forEach(
                item => item.remove());
            return;
        }
        const clear = event.target.closest?.("[data-csv-clear]");
        if (clear) {
            clear.closest("[data-csv-dialog]")?.querySelector(
                "[data-csv-selected-list]")?.replaceChildren();
            return;
        }
        const profile = event.target.closest?.("[data-csv-profile]");
        if (profile) {
            applyCSVExportProfile(profile);
        }
    });

    document.addEventListener("dblclick", function (event) {
        const choice = event.target.closest?.("[data-csv-field-choice]");
        if (!choice) {
            return;
        }
        const list = choice.closest("[data-csv-dialog]")?.querySelector(
            "[data-csv-selected-list]");
        addCSVSelectedField(
            list, choice.dataset.csvField,
            choice.dataset.csvLabel || choice.textContent.trim());
        choice.classList.remove("vs-selected");
    });

    let csvDraggedField = null;
    document.addEventListener("dragstart", function (event) {
        const item = event.target.closest?.("[data-csv-selected-field]");
        if (!item || !event.dataTransfer) {
            return;
        }
        csvDraggedField = item;
        item.classList.add("vs-dragging");
        event.dataTransfer.effectAllowed = "move";
        event.dataTransfer.setData(
            "text/plain", item.dataset.csvSelectedField || "");
    });
    document.addEventListener("dragover", function (event) {
        if (!csvDraggedField) {
            return;
        }
        const target = event.target.closest?.("[data-csv-selected-field]");
        if (!target || target === csvDraggedField ||
                target.parentElement !== csvDraggedField.parentElement) {
            return;
        }
        event.preventDefault();
        const rectangle = target.getBoundingClientRect();
        target.parentElement.insertBefore(
            csvDraggedField,
            event.clientY < rectangle.top + rectangle.height / 2
                ? target : target.nextSibling);
    });
    document.addEventListener("drop", function (event) {
        if (csvDraggedField) {
            event.preventDefault();
        }
    });
    document.addEventListener("dragend", function () {
        csvDraggedField?.classList.remove("vs-dragging");
        csvDraggedField = null;
    });
    document.body.addEventListener(
        "cassini-csv-autodetected", function () {
            const skip = document.querySelector(
                "[data-csv-dialog='import'] [name='skip']");
            if (skip) {
                skip.value = "1";
            }
        });

    function attachmentDropTarget(event) {
        return event.target.closest?.("[data-attachment-drop]");
    }

    document.addEventListener('dragenter', function (event) {
        const target = attachmentDropTarget(event);
        if (!target || !Array.from(
                event.dataTransfer?.types || []).includes("Files")) {
            return;
        }
        event.preventDefault();
        target.classList.add("vs-attachment-drop-active");
    });

    document.addEventListener('dragover', function (event) {
        const target = attachmentDropTarget(event);
        if (!target || !Array.from(
                event.dataTransfer?.types || []).includes("Files")) {
            return;
        }
        event.preventDefault();
        event.dataTransfer.dropEffect = "copy";
        target.classList.add("vs-attachment-drop-active");
    });

    document.addEventListener('dragleave', function (event) {
        const target = attachmentDropTarget(event);
        if (target && !target.contains(event.relatedTarget)) {
            target.classList.remove("vs-attachment-drop-active");
        }
    });

    document.addEventListener('drop', function (event) {
        const target = attachmentDropTarget(event);
        if (!target || !event.dataTransfer?.files?.length) {
            return;
        }
        event.preventDefault();
        target.classList.remove("vs-attachment-drop-active");
        const input = target.querySelector("[data-attachment-input]");
        if (!input) {
            return;
        }
        input.files = event.dataTransfer.files;
        input.dispatchEvent(new Event("change", {bubbles: true}));
    });

    function setTableColumnPixels(table) {
        const columns = Array.from(table.querySelectorAll(
            ":scope > colgroup > col"));
        let width = 0;
        for (const column of columns) {
            const columnWidth = column.getBoundingClientRect().width;
            column.style.width = columnWidth + "px";
            width += columnWidth;
        }
        table.style.width = width + "px";
        return columns;
    }

    function persistTableColumnWidths(table) {
        const url = table.dataset.columnResizeUrl;
        const model = table.dataset.columnModel;
        if (!url || !model) {
            return;
        }
        const widths = {};
        for (const column of table.querySelectorAll(
                ":scope > colgroup > col[data-column-field]")) {
            const name = column.dataset.columnField;
            const occurrence = Number(column.dataset.columnOccurrence || 1);
            if (!name || !Number.isInteger(occurrence) || occurrence < 1) {
                continue;
            }
            if (!widths[name]) {
                widths[name] = [];
            }
            while (widths[name].length < occurrence) {
                widths[name].push(null);
            }
            widths[name][occurrence - 1] = Math.round(
                column.getBoundingClientRect().width);
        }
        const data = new FormData();
        data.set("model", model);
        data.set("widths", JSON.stringify(widths));
        data.set(
            "screen_width",
            Math.round(window.screen.width || window.innerWidth));
        fetch(url, {
            method: "POST",
            body: data,
            credentials: "same-origin",
            headers: {"HX-Request": "true"},
        }).then(function (response) {
            if (!response.ok) {
                throw new Error(tr(
                    "Could not save the column widths."));
            }
        }).catch(function () {
            showClientNotice(tr(
                "Could not save the column widths."), true);
        });
    }

    function copySelectedTreeRecords(action) {
        const table = action.closest(".vs-resizable-table");
        if (!table || !navigator.clipboard) {
            return;
        }
        const fields = Array.from(table.querySelectorAll(
            ":scope > colgroup > col")).map(
                column => Boolean(column.dataset.columnField));
        const rows = Array.from(table.querySelectorAll("tbody > tr")).filter(
            row => row.querySelector('input[name="selected"]:checked'));
        const data = rows.map(function (row) {
            return Array.from(row.children).reduce(
                function (values, cell, index) {
                    if (fields[index]) {
                        values.push('"' + cell.innerText.replaceAll(
                            '"', '""') + '"');
                    }
                    return values;
                }, []).join("\t");
        }).join("\n");
        navigator.clipboard.writeText(data).then(function () {
            action.closest("details")?.removeAttribute("open");
        }).catch(function () {
            showClientNotice(tr(
                "Failed to copy selected records to the clipboard."), true);
        });
    }

    function resetTableColumnWidths(action) {
        const table = action.closest(".vs-resizable-table");
        const url = table?.dataset.columnResizeUrl;
        const model = table?.dataset.columnModel;
        if (!table || !url || !model) {
            return;
        }
        const data = new FormData();
        data.set("model", model);
        data.set("reset", "true");
        data.set(
            "screen_width",
            Math.round(window.screen.width || window.innerWidth));
        fetch(url, {
            method: "POST",
            body: data,
            credentials: "same-origin",
            headers: {"HX-Request": "true"},
        }).then(function (response) {
            if (!response.ok) {
                throw new Error(tr("Could not save the column widths."));
            }
            for (const column of table.querySelectorAll(
                    ":scope > colgroup > col[data-column-field]")) {
                const width = column.dataset.columnDefaultWidth;
                column.style.width = width ? width + "px" : "";
            }
            table.style.width = "";
            action.closest("details")?.removeAttribute("open");
        }).catch(function () {
            showClientNotice(tr(
                "Could not save the column widths."), true);
        });
    }

    function resizeTableColumn(resizer, delta) {
        const header = resizer.closest("th");
        const table = resizer.closest(".vs-resizable-table");
        if (!header || !table) {
            return;
        }
        const headers = Array.from(header.parentElement.children);
        const index = headers.indexOf(header);
        const columns = setTableColumnPixels(table);
        const column = columns[index];
        if (!column) {
            return;
        }
        const oldWidth = column.getBoundingClientRect().width;
        const tableWidth = table.getBoundingClientRect().width;
        const width = Math.max(48, oldWidth + delta);
        column.style.width = width + "px";
        table.style.width = tableWidth + width - oldWidth + "px";
        persistTableColumnWidths(table);
    }

    document.addEventListener("pointerdown", function (event) {
        const resizer = event.target.closest("[data-column-resizer]");
        if (!resizer || (event.button !== undefined && event.button !== 0)) {
            return;
        }
        const header = resizer.closest("th");
        const table = resizer.closest(".vs-resizable-table");
        if (!header || !table) {
            return;
        }
        const headers = Array.from(header.parentElement.children);
        const index = headers.indexOf(header);
        const columns = setTableColumnPixels(table);
        const column = columns[index];
        if (!column) {
            return;
        }
        event.preventDefault();
        event.stopPropagation();
        const startX = event.clientX;
        const startWidth = column.getBoundingClientRect().width;
        const startTableWidth = table.getBoundingClientRect().width;
        table.classList.add("vs-column-resizing");
        resizer.classList.add("vs-column-resizing");
        resizer.setPointerCapture?.(event.pointerId);

        function move(moveEvent) {
            const width = Math.max(
                48, startWidth + moveEvent.clientX - startX);
            column.style.width = width + "px";
            table.style.width =
                startTableWidth + width - startWidth + "px";
        }

        function finish(finishEvent) {
            document.removeEventListener("pointermove", move);
            document.removeEventListener("pointerup", finish);
            document.removeEventListener("pointercancel", cancel);
            resizer.releasePointerCapture?.(finishEvent.pointerId);
            table.classList.remove("vs-column-resizing");
            resizer.classList.remove("vs-column-resizing");
            persistTableColumnWidths(table);
        }

        function cancel(cancelEvent) {
            column.style.width = startWidth + "px";
            table.style.width = startTableWidth + "px";
            finish(cancelEvent);
        }

        document.addEventListener("pointermove", move);
        document.addEventListener("pointerup", finish);
        document.addEventListener("pointercancel", cancel);
    });

    document.addEventListener("input", function (event) {
        const urlInput = event.target.closest("[data-url-input]");
        if (urlInput) {
            syncURLWidget(urlInput.closest("[data-url-widget]"));
        }
        const search = event.target.closest("[data-search-autocomplete]");
        if (search) {
            updateSearchCompletion(search);
        }
        const globalSearch = event.target.closest(
            "[data-global-search-input]");
        if (globalSearch) {
            updateGlobalSearchAssistantTip(globalSearch);
        }
        const welcome = event.target.closest("[data-welcome-search]");
        if (!welcome) {
            return;
        }
        const global = document.querySelector("[data-global-search-input]");
        if (!global) {
            return;
        }
        global.value = welcome.value;
        global.dispatchEvent(new Event("input", {bubbles: true}));
        global.focus({preventScroll: true});
        const end = global.value.length;
        if (global.setSelectionRange) {
            global.setSelectionRange(end, end);
        }
        welcome.value = "";
    });

    document.addEventListener("change", function (event) {
        const popup = event.target.closest(
            ".vs-column-popup .vs-column-option");
        if (popup) {
            pendingColumnPopup = popup.closest(
                ".vs-column-popup")?.dataset.columnPopup || null;
        }
    });

    document.addEventListener("pointerdown", function (event) {
        const numericDisplay = event.target.closest?.(
            "[data-numeric-display]");
        if (activateNumericEditor(numericDisplay)) {
            event.preventDefault();
        }
    });

    document.addEventListener("focusin", function (event) {
        const numericDisplay = event.target.closest?.(
            "[data-numeric-display]");
        activateNumericEditor(numericDisplay, true);
        const search = event.target.closest("[data-search-autocomplete]");
        if (search) {
            updateSearchCompletion(search);
        }
        const globalSearch = event.target.closest(
            "[data-global-search-input]");
        if (globalSearch) {
            updateGlobalSearchAssistantTip(globalSearch);
        }
    });

    document.addEventListener("focusout", function (event) {
        const numericEditor = event.target.closest?.(
            "[data-numeric-editor]");
        if (numericEditor && numericEditor.checkValidity()) {
            const widget = numericEditor.closest("[data-numeric-widget]");
            const display = widget?.querySelector("[data-numeric-display]");
            if (display) {
                const value = numericEditor.value;
                if (!value || widget.dataset.numericKind === "timedelta") {
                    display.value = value;
                } else {
                    const configuredDigits = widget.dataset.numericDigits;
                    const fraction = value.match(/\.(\d+)/)?.[1].length || 0;
                    const digits = configuredDigits === undefined
                        ? fraction : Number(configuredDigits);
                    display.value = new Intl.NumberFormat(
                        document.documentElement.lang || undefined, {
                            useGrouping:
                                widget.dataset.numericGrouping !== "false",
                            minimumFractionDigits: digits,
                            maximumFractionDigits: digits,
                        }).format(Number(value));
                }
                numericEditor.hidden = true;
                display.hidden = false;
            }
        }
        const globalSearch = event.target.closest(
            "[data-global-search-input]");
        if (globalSearch) {
            globalSearch.closest(".vs-global-search-entry")?.classList.remove(
                "vs-global-search-assistant-tip-visible");
        }
    });

    document.addEventListener("click", function (event) {
        const copySelected = event.target.closest(
            "[data-copy-selected-records]");
        if (copySelected) {
            copySelectedTreeRecords(copySelected);
            return;
        }
        const resetWidths = event.target.closest(
            "[data-reset-column-widths]");
        if (resetWidths) {
            resetTableColumnWidths(resetWidths);
            return;
        }
        const relation = event.target.closest("[data-relation-open]");
        if (!relation || (!event.ctrlKey && !event.metaKey)) {
            return;
        }
        event.preventDefault();
        event.stopPropagation();
        const url = relation.dataset.openTabUrl;
        if (!url) {
            return;
        }
        window.htmx.ajax("POST", url, {
            target: "#workspace",
            swap: "outerHTML",
            pushUrl: true,
        });
    }, true);
    document.addEventListener("click", function (event) {
        const popupAction = event.target.closest(
            "[data-dismiss-popup-client]");
        if (popupAction) {
            const container = popupAction.closest(
                "[data-dismissible-popup-container]");
            const popup = container?.querySelector(
                "[data-dismissible-popup]");
            popup?.remove();
            container?.querySelector("[aria-expanded]")?.setAttribute(
                "aria-expanded", "false");
        }
        dismissPopupsOutside(event.target);
        if (event.target.closest("[data-close-relation-modal]")) {
            document.getElementById("relation-modal")?.replaceChildren();
            return;
        }
        const relationSearchRow = event.target.closest(
            "[data-relation-search-row]");
        if (relationSearchRow &&
                !event.target.closest("[data-relation-select-action]")) {
            const input = relationSearchRow.querySelector(
                'input[name="value"]');
            const form = relationSearchRow.closest(
                ".vs-relation-selection-form");
            if (input && event.detail > 1) {
                input.checked = true;
            } else if (input &&
                    !event.target.matches('input[name="value"]')) {
                input.checked = input.type === "radio" ? true : !input.checked;
            }
            for (const row of form?.querySelectorAll(
                    "[data-relation-search-row]") || []) {
                row.classList.toggle(
                    "vs-row-current",
                    Boolean(row.querySelector(
                        'input[name="value"]:checked')));
            }
            const confirm = form?.querySelector(
                "[data-relation-search-confirm]");
            if (confirm) {
                confirm.disabled = !form.querySelector(
                    'input[name="value"]:checked');
            }
        }
        const preferenceTab = event.target.closest(
            "[data-preference-notebook-tab][role='tab']");
        if (preferenceTab) {
            const notebook = preferenceTab.closest(".vs-notebook");
            const page = preferenceTab.dataset.preferenceNotebookPage;
            for (const button of notebook.querySelectorAll(
                    "[data-preference-notebook-tab][role='tab']")) {
                const selected =
                    button.dataset.preferenceNotebookPage === page;
                button.setAttribute(
                    "aria-selected", selected ? "true" : "false");
                button.closest(".vs-local-tab")?.classList.toggle(
                    "vs-local-tab-active", selected);
            }
            for (const panel of notebook.querySelectorAll(
                    "[data-preference-notebook-tab][role='tabpanel']")) {
                panel.hidden =
                    panel.dataset.preferenceNotebookPage !== page;
            }
        }
        for (const popup of document.querySelectorAll(
                "details.vs-popup[open]")) {
            if (!popup.contains(event.target)) {
                popup.open = false;
            }
        }
        const searchCompletion = event.target.closest(
            "[data-search-completion-option]");
        if (searchCompletion) {
            const form = searchCompletion.closest(".vs-search-form");
            const input = form?.querySelector(
                "[data-search-autocomplete]");
            if (input) {
                event.preventDefault();
                input.value =
                    searchCompletion.dataset.searchCompletionOption || "";
                closeSearchCompletion(input);
                input.focus({preventScroll: true});
                const end = input.value.length;
                if (input.setSelectionRange) {
                    input.setSelectionRange(end, end);
                }
                input.dispatchEvent(new Event("input", {bubbles: true}));
                closeSearchCompletion(input);
            }
            return;
        }
        if (!event.target.closest(".vs-search-form")) {
            for (const input of document.querySelectorAll(
                    "[data-search-autocomplete]")) {
                closeSearchCompletion(input);
            }
        }
        const globalSearchResult = event.target.closest(
            "[data-global-search-result]");
        if (globalSearchResult) {
            const search = globalSearchResult.closest("#global-search");
            const input = search?.querySelector(
                "[data-global-search-input]");
            if (input) {
                window.htmx.trigger(input, "htmx:abort");
                input.value = "";
            }
            const results = search?.querySelector(".vs-search-results");
            // Hide the popup immediately but keep the clicked HTMX element
            // connected until its request and target swap have completed.
            if (results) {
                results.hidden = true;
                globalSearchResult.addEventListener(
                    "htmx:afterRequest", () => results.remove(),
                    {once: true});
            }
        }
        const userItem = event.target.closest(
            ".vs-user-menu [role='menuitem']");
        if (userItem) {
            const menu = userItem.closest(".vs-user-menu");
            if (menu) {
                menu.hidden = true;
            }
        }
        if (event.target.closest("[data-close-modal]")) {
            closeModal();
        }
        const fullscreen = event.target.closest("[data-toggle-fullscreen]");
        if (fullscreen) {
            if (document.fullscreenElement) {
                document.exitFullscreen();
            } else {
                document.documentElement.requestFullscreen();
            }
        }
        const menuItem = event.target.closest(".vs-popup-item");
        if (menuItem) {
            const popup = menuItem.closest("details");
            if (popup) {
                popup.open = false;
            }
        }
        const share = event.target.closest("[data-share-tab]");
        if (share) {
            event.preventDefault();
            shareTab(share).catch(error => {
                showClientNotice(error.message, true);
            });
        }
        const toolbarPopupItem = event.target.closest(
            "[data-open-toolbar-popup]");
        if (toolbarPopupItem) {
            const screen = toolbarPopupItem.closest(".vs-screen");
            const category =
                toolbarPopupItem.dataset.openToolbarPopup;
            const popup = screen?.querySelector(
                `details.vs-action-popup[data-action-category="${category}"]`);
            if (popup) {
                popup.open = true;
                popup.querySelector("summary")?.focus({preventScroll: true});
            }
        }
        const row = treeRowFromEvent(event, true);
        if (row) {
            const selectAction = row.querySelector(
                "[data-row-select-action]");
            const selectionKind = selectAction?.dataset.rowSelectionKind;
            const multipleSelection =
                selectionKind === "screen" || selectionKind === "relation";
            const selection = markTreeRowSelected(
                row, event, multipleSelection);
            window.clearTimeout(rowClickTimer);
            rowClickTimer = window.setTimeout(function () {
                if (selectAction) {
                    if (multipleSelection && selection) {
                        const values = {
                            selection: JSON.stringify(selection.records),
                            current: selection.current,
                        };
                        if (selectionKind === "relation") {
                            values.item = row.dataset.record;
                        }
                        selectAction.setAttribute(
                            "hx-vals", JSON.stringify(values));
                    }
                    selectAction.click();
                }
                rowClickTimer = null;
            }, 220);
        }
    });
    document.addEventListener("dblclick", function (event) {
        const relationSearchRow = event.target.closest(
            "[data-relation-search-row]");
        if (relationSearchRow) {
            event.preventDefault();
            const form = relationSearchRow.closest(
                ".vs-relation-selection-form");
            const input = relationSearchRow.querySelector(
                'input[name="value"]');
            if (input) {
                input.checked = true;
            }
            const confirm = form?.querySelector(
                "[data-relation-search-confirm]");
            if (confirm) {
                confirm.disabled = false;
                window.htmx.trigger(form, "submit");
            }
            return;
        }
        const row = treeRowFromEvent(event, true);
        if (!row) {
            return;
        }
        event.preventDefault();
        window.clearTimeout(rowClickTimer);
        rowClickTimer = null;
        const openAction = row.querySelector("[data-row-open-action]");
        if (openAction) {
            openAction.click();
        }
    }, true);
    document.addEventListener("keydown", function (event) {
        const temporal = event.target.closest?.("[data-temporal-input]");
        if (temporal && !temporal.disabled && !temporal.readOnly &&
                !event.ctrlKey && !event.altKey && !event.metaKey &&
                !event.isComposing) {
            const operators = {
                S: ["second", -1], s: ["second", 1],
                I: ["minute", -1], i: ["minute", 1],
                H: ["hour", -1], h: ["hour", 1],
                D: ["day", -1], d: ["day", 1],
                W: ["week", -1], w: ["week", 1],
                M: ["month", -1], m: ["month", 1],
                Y: ["year", -1], y: ["year", 1],
            };
            if (event.key === "Enter") {
                const parsed = temporalParse(temporal);
                if (parsed) {
                    event.preventDefault();
                    setTemporalValue(temporal, parsed);
                    temporal.dispatchEvent(new Event(
                        "change", {bubbles: true}));
                }
                return;
            }
            if (event.key === "=" || operators[event.key]) {
                event.preventDefault();
                let value = (
                    event.key === "=" ? new Date() :
                    temporalParse(temporal) || new Date());
                if (operators[event.key]) {
                    value = adjustTemporal(
                        value,
                        operators[event.key][0],
                        operators[event.key][1]);
                }
                setTemporalValue(temporal, value);
                temporal.dispatchEvent(new Event(
                    "change", {bubbles: true}));
                return;
            }
        }
        const resizer = event.target.closest?.("[data-column-resizer]");
        if (resizer && (event.key === "ArrowLeft"
                || event.key === "ArrowRight")) {
            event.preventDefault();
            resizeTableColumn(
                resizer, event.key === "ArrowLeft" ? -16 : 16);
            return;
        }
        const search = event.target.closest("[data-search-autocomplete]");
        if (search) {
            const completion = search.closest(
                ".vs-search-form")?.querySelector(
                    "[data-search-completion-list]");
            if (event.key === "Escape" && completion && !completion.hidden) {
                event.preventDefault();
                closeSearchCompletion(search);
                return;
            }
            if (event.key === "ArrowDown" && completion &&
                    !completion.hidden) {
                const first = Array.from(completion.querySelectorAll(
                    "[data-search-completion-option]")).find(
                        option => !option.hidden);
                if (first) {
                    event.preventDefault();
                    first.focus();
                    return;
                }
            }
        }
        const searchOption = event.target.closest(
            "[data-search-completion-option]");
        if (searchOption && event.key === "Escape") {
            const input = searchOption.closest(
                ".vs-search-form")?.querySelector(
                    "[data-search-autocomplete]");
            if (input) {
                event.preventDefault();
                closeSearchCompletion(input);
                input.focus({preventScroll: true});
                return;
            }
        }
        if (event.key === "Escape") {
            if (cancelTopModal()) {
                event.preventDefault();
                event.stopImmediatePropagation();
            }
        }
    });
    document.addEventListener("change", function (event) {
        const picker = event.target.closest?.(
            "[data-temporal-picker-input]");
        if (picker?.value) {
            const input = picker.closest("[data-temporal-widget]")
                ?.querySelector("[data-temporal-input]");
            if (!input) {
                return;
            }
            const parts = picker.value.split(/[T:-]/).map(Number);
            let value;
            if (input.dataset.temporalKind === "date") {
                value = new Date(parts[0], parts[1] - 1, parts[2]);
            } else if (input.dataset.temporalKind === "time") {
                const now = new Date();
                value = new Date(
                    now.getFullYear(), now.getMonth(), now.getDate(),
                    parts[0], parts[1], parts[2] || 0);
            } else {
                value = new Date(
                    parts[0], parts[1] - 1, parts[2],
                    parts[3], parts[4], parts[5] || 0);
            }
            setTemporalValue(input, value);
            input.dispatchEvent(new Event("change", {bubbles: true}));
            return;
        }
        const input = event.target.closest?.("[data-temporal-input]");
        if (input) {
            const value = temporalParse(input);
            if (value) {
                setTemporalValue(input, value);
            }
        }
    }, true);
    document.addEventListener("keydown", function (event) {
        if (event.defaultPrevented || event.isComposing || event.repeat) {
            return;
        }
        const definition = shortcutDefinitions.find(
            item => matchesShortcut(event, item));
        if (!definition ||
                document.querySelector(".vs-modal-backdrop")) {
            return;
        }
        event.preventDefault();
        event.stopImmediatePropagation();
        activateShortcut(definition.action);
    });
    document.addEventListener("change", function (event) {
        const input = event.target.closest("[data-relation-input]");
        if (input) {
            const list = document.getElementById(input.getAttribute("list"));
            const hidden = document.getElementById(
                input.dataset.relationValue);
            if (!list || !hidden) {
                return;
            }
            const match = Array.from(list.options).find(
                option => option.value === input.value);
            hidden.value = match ? match.dataset.id : "";
            hidden.dispatchEvent(new Event("change", {bubbles: true}));
        }
        const x2manyInput = event.target.closest("[data-x2many-input]");
        if (x2manyInput) {
            const list = document.getElementById(
                x2manyInput.getAttribute("list"));
            const hidden = document.getElementById(
                x2manyInput.dataset.x2manyValue);
            if (!list || !hidden) {
                return;
            }
            const match = Array.from(list.options).find(
                option => option.value === x2manyInput.value);
            hidden.value = match ? match.dataset.id : "";
        }
    });
    document.addEventListener("click", function (event) {
        const choice = event.target.closest("[data-relation-choice]");
        if (choice) {
            const widget = choice.closest("[data-relation-widget]");
            const input = widget?.querySelector("[data-relation-input]");
            const hidden = widget?.querySelector("[data-relation-hidden]");
            if (!input || !hidden) {
                return;
            }
            input.value = choice.dataset.relationTitle || choice.textContent;
            input.dataset.relationSelectedTitle = input.value;
            hidden.value = choice.dataset.relationChoice || "";
            const completion = widget.querySelector(
                ".vs-relation-completion");
            if (completion) {
                completion.dataset.open = "false";
            }
            hidden.dispatchEvent(new Event("change", {bubbles: true}));
            input.focus();
            return;
        }
        const clear = event.target.closest("[data-relation-clear]");
        if (clear) {
            const widget = clear.closest("[data-relation-widget]");
            const input = widget?.querySelector("[data-relation-input]");
            const hidden = widget?.querySelector("[data-relation-hidden]");
            if (!input || !hidden) {
                return;
            }
            input.value = "";
            input.dataset.relationSelectedTitle = "";
            hidden.value = "";
            hidden.dispatchEvent(new Event("change", {bubbles: true}));
            input.focus();
            return;
        }
    });
    document.addEventListener("keydown", function (event) {
        const completionOption = event.target.closest?.(
            ".vs-relation-option, .vs-relation-completion-action");
        if (completionOption && [
                "ArrowDown", "ArrowUp", "Home", "End",
            ].includes(event.key)) {
            const completion = completionOption.closest(
                ".vs-relation-completion");
            const options = Array.from(completion?.querySelectorAll(
                ".vs-relation-option:not(:disabled), " +
                ".vs-relation-completion-action:not(:disabled)") || []);
            if (options.length) {
                event.preventDefault();
                let index = options.indexOf(completionOption);
                if (event.key === "Home") {
                    index = 0;
                } else if (event.key === "End") {
                    index = options.length - 1;
                } else {
                    index += event.key === "ArrowDown" ? 1 : -1;
                    index = (index + options.length) % options.length;
                }
                options[index].focus({preventScroll: true});
            }
            return;
        }
        const input = event.target.closest("[data-x2many-add-input]");
        if (!input) {
            return;
        }
        const widget = input.closest("[data-x2many-add-widget]");
        const completion = widget?.querySelector(
            ".vs-relation-completion");
        if (event.key === "F3") {
            event.preventDefault();
            completion?.querySelector(
                ".vs-relation-completion-action[hx-post]")?.click();
            return;
        }
        if (event.key === "F2") {
            event.preventDefault();
            input.closest(".vs-x2many-toolbar")?.querySelector(
                "[data-x2many-add]")?.click();
            return;
        }
        if (event.key === "Escape") {
            input.value = "";
            if (completion) {
                completion.dataset.open = "false";
            }
            return;
        }
        if (event.key === "ArrowDown") {
            const option = completion?.querySelector(
                ".vs-relation-option, .vs-relation-completion-action");
            if (option) {
                event.preventDefault();
                option.focus();
            }
            return;
        }
        if (event.key === "Enter" && input.value) {
            event.preventDefault();
            const option = completion?.querySelector(
                ".vs-relation-option");
            if (option) {
                option.click();
            } else {
                input.closest(".vs-x2many-toolbar")?.querySelector(
                    "[data-x2many-add]")?.click();
            }
        }
    });
    document.addEventListener("keydown", function (event) {
        const input = event.target.closest("[data-relation-input]");
        if (!input) {
            return;
        }
        const widget = input.closest("[data-relation-widget]");
        const hidden = widget?.querySelector("[data-relation-hidden]");
        if (!hidden) {
            return;
        }
        if (event.key === "F3") {
            event.preventDefault();
            widget.querySelector(
                ".vs-relation-completion-action[hx-post]")?.click();
            return;
        }
        if (event.key === "F2") {
            event.preventDefault();
            if (hidden.value) {
                widget.querySelector(
                    ".vs-relation-icon-primary")?.click();
            } else {
                widget.querySelector(
                    ".vs-relation-icon-secondary, " +
                    ".vs-relation-completion-action")?.click();
            }
            return;
        }
        if (event.key === "Escape") {
            input.value = input.dataset.relationSelectedTitle || "";
            const completion = widget.querySelector(
                ".vs-relation-completion");
            if (completion) {
                completion.dataset.open = "false";
            }
            return;
        }
        if (event.key === "ArrowDown") {
            const option = widget.querySelector(
                ".vs-relation-option, .vs-relation-completion-action");
            if (option) {
                event.preventDefault();
                option.focus();
            }
            return;
        }
        if ((event.key === "Backspace" || event.key === "Delete")
                && hidden.value
                && input.value === input.dataset.relationSelectedTitle) {
            input.value = "";
            input.dataset.relationSelectedTitle = "";
            hidden.value = "";
            hidden.dispatchEvent(new Event("change", {bubbles: true}));
        }
    });
    document.addEventListener("keydown", function (event) {
        const filename = event.target.closest?.("[data-binary-filename]");
        if (!filename) {
            return;
        }
        const widget = filename.closest(".vs-binary-widget");
        if (event.key === "F3" && !filename.disabled && !filename.readOnly) {
            event.preventDefault();
            widget?.querySelector("[data-binary-select] input")?.click();
            return;
        }
        if (event.key === "F2") {
            event.preventDefault();
            widget?.querySelector(".vs-binary-actions a")?.click();
        }
    });
    document.addEventListener("keydown", function (event) {
        if (event.key !== "Enter" || event.defaultPrevented ||
                event.isComposing || event.shiftKey || event.ctrlKey ||
                event.altKey || event.metaKey) {
            return;
        }
        const input = event.target.closest?.(
            "[data-editable-tree='true'] .vs-row input, " +
            "[data-editable-tree='true'] .vs-row select");
        if (!input || input.matches(
                "[data-relation-input], [data-x2many-add-input], " +
                "[data-temporal-input], input[type='checkbox'], " +
                "input[type='radio'], input[type='file']")) {
            return;
        }
        const table = input.closest("[data-editable-tree='true']");
        const create = function () {
            const embedded = table.querySelector(
                "[data-editable-tree-new]");
            const main = table.closest(".vs-screen")?.querySelector(
                "[data-shortcut-action='new']");
            (embedded || main)?.click();
        };
        event.preventDefault();
        event.stopPropagation();
        let completed = false;
        const finish = function () {
            if (completed) {
                return;
            }
            completed = true;
            document.body.removeEventListener(
                "htmx:afterRequest", afterRequest);
            window.clearTimeout(timeout);
            create();
        };
        const afterRequest = function (requestEvent) {
            if (requestEvent.detail?.elt === input) {
                finish();
            }
        };
        document.body.addEventListener("htmx:afterRequest", afterRequest);
        const timeout = window.setTimeout(finish, 650);
        input.dispatchEvent(new Event("change", {bubbles: true}));
        if (!input.hasAttribute("hx-post")) {
            finish();
        }
    });
    document.addEventListener("click", function (event) {
        const shortcutHelp = event.target.closest("[data-shortcut-help]");
        if (shortcutHelp) {
            showShortcutHelp();
            return;
        }
        const upload = event.target.closest("[data-help-upload]");
        if (upload) {
            chatFileInput(upload)?.click();
            return;
        }
        const remove = event.target.closest("[data-remove-chat-file]");
        if (remove) {
            removeChatFile(remove);
            return;
        }
        const capture = event.target.closest("[data-help-capture]");
        if (capture) {
            captureScreenshot(capture);
            return;
        }
        const recording = event.target.closest("[data-help-record]");
        if (recording) {
            toggleScreenRecording(recording);
            return;
        }
        const voice = event.target.closest("[data-help-voice]");
        if (voice) {
            toggleVoiceRecording(voice);
            return;
        }
        const speech = event.target.closest("[data-help-speech]");
        if (speech) {
            speechEnabled = !speechEnabled;
            speech.classList.toggle("vs-recording", speechEnabled);
            if (speechEnabled) {
                speakAssistant(speech.closest("#help-panel"), true);
            }
            return;
        }
        const cobrowse = event.target.closest("[data-help-cobrowse]");
        if (cobrowse) {
            if (typeof window.cobrowsingPopup === "function") {
                window.cobrowsingPopup();
            } else {
                openCobrowsingPopup();
            }
            return;
        }
        const startCobrowse = event.target.closest("[data-start-cobrowse]");
        if (startCobrowse) {
            startCobrowse.disabled = true;
            initializeSurfly().then(function (surfly) {
                surfly.session().startLeader();
                closeModal();
            }).catch(function (error) {
                startCobrowse.disabled = false;
                showClientNotice(error.message, true);
            });
        }
    });
    document.addEventListener("change", function (event) {
        const input = event.target.closest("[data-chat-files]");
        if (input) {
            renderChatFiles(input);
        }
    });
    function updateGlobalSearchAssistantTip(input) {
        const entry = input?.closest(".vs-global-search-entry");
        if (!entry) {
            return;
        }
        entry.classList.toggle(
            "vs-global-search-assistant-tip-visible",
            input.matches("[data-global-search-assistant]")
            && input === document.activeElement
            && Boolean(input.value.trim()));
    }

    function sendGlobalSearchToAssistant(input) {
        const text = input?.value.trim();
        if (!text) {
            return false;
        }
        window.htmx.trigger(input, "htmx:abort");
        input.value = "";
        updateGlobalSearchAssistantTip(input);
        input.closest("#global-search")?.querySelector(
            ".vs-search-results")?.remove();

        const send = function () {
            const message = document.querySelector(
                "[data-chat-form] #message");
            const submit = message?.closest("form")?.querySelector(
                "[data-chat-send]");
            if (!message || !submit || submit.disabled) {
                return;
            }
            message.value = text;
            const form = message.closest("form");
            window.htmx.ajax("POST", form.getAttribute("hx-post"), {
                source: form,
                target: "#help-panel",
                swap: "outerHTML",
            });
        };
        const help = document.querySelector("[data-panel-option='help']");
        if (help?.getAttribute("aria-pressed") === "true") {
            send();
        } else if (help) {
            window.htmx.ajax("POST", help.getAttribute("hx-post"), {
                source: help,
                target: "#cassini",
                swap: "outerHTML",
            }).then(send);
        }
        return true;
    }

    document.addEventListener("mousedown", function (event) {
        if (event.target.closest("[data-global-search-assistant-tip]")) {
            event.preventDefault();
        }
    });
    document.addEventListener("click", function (event) {
        const tip = event.target.closest("[data-global-search-assistant-tip]");
        if (!tip) {
            return;
        }
        const input = tip.closest("#global-search")?.querySelector(
            "[data-global-search-input]");
        if (sendGlobalSearchToAssistant(input)) {
            event.preventDefault();
        }
    });
    document.addEventListener("keydown", function (event) {
        const globalSearch = event.target.closest(
            "[data-global-search-input]");
        if (globalSearch && event.key === "ArrowDown" &&
                !event.shiftKey && !event.ctrlKey && !event.altKey &&
                !event.metaKey) {
            const result = globalSearch.closest("#global-search")?.querySelector(
                "[data-global-search-result]");
            if (result) {
                event.preventDefault();
                result.focus({preventScroll: true});
            }
            return;
        }
        const globalSearchResult = event.target.closest(
            "[data-global-search-result]");
        if (globalSearchResult &&
                (event.key === "ArrowDown" || event.key === "ArrowUp") &&
                !event.shiftKey && !event.ctrlKey && !event.altKey &&
                !event.metaKey) {
            const search = globalSearchResult.closest("#global-search");
            const results = Array.from(search?.querySelectorAll(
                "[data-global-search-result]") || []);
            const index = results.indexOf(globalSearchResult);
            const next = index + (event.key === "ArrowDown" ? 1 : -1);
            if (next >= 0 && next < results.length) {
                event.preventDefault();
                results[next].focus({preventScroll: true});
            } else if (next < 0) {
                event.preventDefault();
                search?.querySelector("[data-global-search-input]")?.focus(
                    {preventScroll: true});
            }
            return;
        }
        if (globalSearch && event.key === "Enter" &&
                !event.isComposing && !event.shiftKey &&
                !event.ctrlKey && !event.altKey && !event.metaKey) {
            if (!globalSearch.matches("[data-global-search-assistant]")
                    || !sendGlobalSearchToAssistant(globalSearch)) {
                return;
            }
            event.preventDefault();
            event.stopImmediatePropagation();
            return;
        }
        const input = event.target.closest(
            "[data-chat-form] #message");
        if (!input || event.isComposing) {
            return;
        }
        if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            if (input.value.trim()) {
                input.closest("form").querySelector(
                    "[data-chat-send]")?.click();
            }
        }
    });
    document.addEventListener("dragover", function (event) {
        const input = event.target.closest(
            "[data-chat-form] #message");
        if (input && event.dataTransfer?.types.includes("Files")) {
            event.preventDefault();
            input.classList.add("vs-dragging");
        }
    });
    document.addEventListener("dragleave", function (event) {
        event.target.closest(
            "[data-chat-form] #message")?.classList.remove("vs-dragging");
    });
    document.addEventListener("drop", function (event) {
        const message = event.target.closest(
            "[data-chat-form] #message");
        if (!message || !event.dataTransfer?.files.length) {
            return;
        }
        event.preventDefault();
        message.classList.remove("vs-dragging");
        addChatFiles(
            message.closest("form").querySelector("[data-chat-files]"),
            event.dataTransfer.files);
    });
    document.addEventListener("paste", function (event) {
        const message = event.target.closest(
            "[data-chat-form] #message");
        if (!message) {
            return;
        }
        const files = Array.from(event.clipboardData?.items || [])
            .filter(item => item.kind === "file")
            .map(item => item.getAsFile())
            .filter(Boolean);
        if (files.length) {
            addChatFiles(
                message.closest("form").querySelector("[data-chat-files]"),
                files);
        }
    });
    document.addEventListener("click", function (event) {
        if (!event.target.closest?.("[data-panel-option]")) {
            return;
        }
        captureSidebarWidth(false);
        window.clearTimeout(sidebarWidthTimer);
        sidebarWidthTimer = null;
    }, true);
    document.addEventListener("htmx:beforeRequest", function () {
        rememberFocus();
    });
    document.addEventListener("htmx:confirm", function (event) {
        const message = event.detail && event.detail.question;
        if (!message) {
            return;
        }
        event.preventDefault();
        requestConfirmation(message).then(function (accepted) {
            if (accepted) {
                event.detail.issueRequest(true);
            }
        });
    });
    document.addEventListener(
        "htmx:beforeSwap", prepareFocusedPreservation);
    document.addEventListener("htmx:beforeSwap", function (event) {
        const responseURL = event.detail?.xhr?.responseURL;
        if (!responseURL || !document.querySelector(".vs-shell")) {
            return;
        }
        const url = new URL(responseURL, window.location.href);
        if (url.pathname.endsWith("/cassini/login")) {
            event.detail.shouldSwap = false;
            window.location.replace(url.href);
        }
    });
    document.addEventListener("htmx:afterSwap", function (event) {
        restoreFocus();
        initializeSearchCompletions();
        focusPendingSearch();
        scheduleInitialFormFocus();
        syncShellState();
        syncWorkspaceStickyOffsets();
        window.requestAnimationFrame(syncWorkspaceStickyOffsets);
        scheduleChatPolling();
        initializeHelp();
        initializeSeasonalLogo();
        initializeDynamicWidgets();
        scheduleNoticeDismissal();
        if (pendingColumnPopup) {
            const popup = Array.from(document.querySelectorAll(
                ".vs-column-popup")).find(
                candidate => candidate.dataset.columnPopup
                    === pendingColumnPopup);
            if (popup) {
                popup.open = true;
            }
            pendingColumnPopup = null;
        }
    });
    document.addEventListener("htmx:beforeCleanupElement", function (event) {
        const root = event.detail?.elt;
        if (!root) {
            return;
        }
        const codeWidgets = root.matches?.("[data-code-widget]")
            ? [root] : Array.from(root.querySelectorAll?.(
                "[data-code-widget]") || []);
        codeWidgets.forEach(widget => widget._cassiniEditor?.dispose());
        const charts = root.matches?.("[data-cassini-chart]")
            ? [root] : Array.from(root.querySelectorAll?.(
                "[data-cassini-chart]") || []);
        if (window.Plotly?.purge) {
            charts.forEach(chart => window.Plotly.purge(chart));
        }
    });
    document.addEventListener(
        "htmx:afterRequest", scheduleInitialFormFocus);
    document.addEventListener("htmx:responseError", function (event) {
        const host = document.getElementById("notifications");
        if (!host) {
            return;
        }
        const notice = document.createElement("div");
        notice.className = "vs-notice vs-notice-error";
        notice.textContent = event.detail.xhr.responseText ||
            tr("The server could not complete this action.");
        host.replaceChildren(notice);
        scheduleNoticeDismissal();
    });

    const deferredScreenActions = new Set();
    const pendingFieldRequests = new WeakMap();

    function editorValue(editor) {
        return editor?.value ?? "";
    }

    document.addEventListener("focusin", function (event) {
        const editor = event.target.closest?.(
            "input[hx-post], textarea[hx-post]");
        if (editor && editor.dataset.serverValue === undefined) {
            editor.dataset.serverValue = editor.defaultValue ?? editorValue(editor);
        }
    });

    document.addEventListener("htmx:beforeRequest", function (event) {
        const editor = event.detail?.elt;
        if (!editor?.matches?.("input[hx-post], textarea[hx-post]")) {
            return;
        }
        const owner = editor.closest(".vs-screen, .vs-wizard");
        if (!owner) {
            return;
        }
        const pending = Number(owner.dataset.pendingFieldRequests || 0) + 1;
        owner.dataset.pendingFieldRequests = String(pending);
        const request = event.detail?.xhr || editor;
        pendingFieldRequests.set(request, {
            ownerId: owner.id,
            editor: editor,
            value: editorValue(editor),
        });
    });

    document.addEventListener("htmx:afterSettle", function (event) {
        const request = event.detail?.xhr || event.detail?.elt;
        const fieldRequest = request && pendingFieldRequests.get(request);
        if (!fieldRequest) {
            return;
        }
        pendingFieldRequests.delete(request);
        if (fieldRequest.editor.isConnected &&
                editorValue(fieldRequest.editor) === fieldRequest.value) {
            fieldRequest.editor.dataset.serverValue = fieldRequest.value;
        }
        const owner = document.getElementById(fieldRequest.ownerId);
        if (!owner) {
            return;
        }
        const pending = Math.max(
            0, Number(owner.dataset.pendingFieldRequests || 0) - 1);
        if (pending) {
            owner.dataset.pendingFieldRequests = String(pending);
        } else {
            delete owner.dataset.pendingFieldRequests;
        }
    });

    function deferActionUntilFieldsAreStored(event) {
        const action = event.target.closest(
            "button[hx-post], button[hx-get], a[hx-post], a[hx-get]");
        if (!action || action.matches("input, textarea, select")) {
            return;
        }
        const screenOwner = action.dataset.screenOwner;
        const owner = action.closest(".vs-screen, .vs-wizard") ||
            (screenOwner ? document.getElementById(screenOwner) : null);
        if (!owner) {
            return;
        }
        const editor = document.activeElement;
        if (editor && editor !== action && owner.contains(editor) &&
                editor.matches("input[hx-post], textarea[hx-post]") &&
                editorValue(editor) !== (
                    editor.dataset.serverValue ?? editor.defaultValue ?? "")) {
            editor.dispatchEvent(new Event("change", {bubbles: true}));
        }
        if (!owner.querySelector(".htmx-request") &&
                !owner.dataset.pendingFieldRequests) {
            return;
        }
        event.preventDefault();
        event.stopImmediatePropagation();
        const ownerId = owner.id;
        const method = action.hasAttribute("hx-post") ? "hx-post" : "hx-get";
        const url = action.getAttribute(method);
        const shortcut = action.getAttribute("data-shortcut-action");
        const key = ownerId + "\n" + method + "\n" + url;
        if (deferredScreenActions.has(key)) {
            return;
        }
        deferredScreenActions.add(key);
        const started = Date.now();
        const resume = function () {
            const currentOwner = document.getElementById(ownerId);
            if (!currentOwner) {
                deferredScreenActions.delete(key);
                return;
            }
            if (currentOwner.querySelector(".htmx-request") ||
                    currentOwner.dataset.pendingFieldRequests) {
                if (Date.now() - started < 10000) {
                    window.setTimeout(resume, 25);
                } else {
                    deferredScreenActions.delete(key);
                }
                return;
            }
            let currentAction = null;
            if (shortcut) {
                currentAction = currentOwner.querySelector(
                    "[data-shortcut-action=\"" +
                    CSS.escape(shortcut) + "\"]");
            }
            if (!currentAction) {
                currentAction = Array.from(currentOwner.querySelectorAll(
                    "[" + method + "]")).find(
                        candidate => candidate.getAttribute(method) === url);
            }
            if (!currentAction && action.dataset.screenOwner) {
                currentAction = Array.from(document.querySelectorAll(
                    "[data-screen-owner=\"" + CSS.escape(ownerId) +
                    "\"][" + method + "]")).find(
                        candidate => candidate.getAttribute(method) === url);
            }
            deferredScreenActions.delete(key);
            if (currentAction && !currentAction.disabled) {
                currentAction.click();
            }
        };
        window.setTimeout(resume, 25);
    }

    document.addEventListener("click", deferActionUntilFieldsAreStored, true);

    document.addEventListener("mousedown", function (event) {
        const option = event.target.closest(
            ".vs-field[data-widget='multiselection'] " +
            "select[multiple] option");
        if (!option || option.disabled) {
            return;
        }
        event.preventDefault();
        const select = option.closest("select");
        const scrollTop = select.scrollTop;
        option.selected = !option.selected;
        select.focus();
        select.dispatchEvent(new Event("change", {bubbles: true}));
        window.requestAnimationFrame(function () {
            select.scrollTop = scrollTop;
        });
    });
    document.addEventListener("click", function (event) {
        if (!event.target.closest?.("[hx-post], [hx-get]")) {
            return;
        }
        for (const delay of [75, 200, 500, 1000]) {
            window.setTimeout(() => focusInitialForm(true), delay);
        }
    });

    window.addEventListener("DOMContentLoaded", function () {
        document.addEventListener("voyager-download", function (event) {
            startDownloads(event.detail && (
                event.detail.value || event.detail));
        });
        document.addEventListener("cassini-open-url", function (event) {
            openURLs(event.detail && (
                event.detail.value || event.detail));
        });
        window.htmx.config.historyCacheSize = 0;
        syncShellState();
        syncWorkspaceStickyOffsets();
        window.requestAnimationFrame(syncWorkspaceStickyOffsets);
        scheduleChatPolling();
        initializeHelp();
        initializeSeasonalLogo();
        initializeSearchCompletions();
        initializeDynamicWidgets();
        scheduleInitialFormFocus();
    });
    window.addEventListener("load", syncWorkspaceStickyOffsets);
    window.addEventListener("resize", syncWorkspaceStickyOffsets);
    document.addEventListener(
        "scroll", scheduleWorkspaceStickyOffsets, true);
}());
