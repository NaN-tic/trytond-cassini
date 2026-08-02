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
    const requestQueues = new WeakMap();
    const replaceRequests = new WeakMap();
    const fallbackTimers = new WeakMap();
    const observedWorkspaceTabs = new WeakSet();

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
        {shortcut: "Alt+Shift+Tab", label: tr("Previous tab"),
            action: "previous-tab", key: "tab", alt: true, shift: true,
            scope: "global"},
        {shortcut: "Alt+Tab", label: tr("Next tab"), action: "next-tab",
            key: "tab", alt: true, scope: "global"},
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
    }

    function syncWorkspaceStickyOffsets() {
        for (const workspace of document.querySelectorAll(".vs-workspace")) {
            const tabs = workspace.querySelector(":scope > .vs-tabs");
            if (!tabs) {
                workspace.style.removeProperty("--vs-tabs-height");
                continue;
            }
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
                term.textContent = definition.label;
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
            return showShortcutHelp();
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
            const searchableView = screen.querySelector(
                "[data-view-type='tree'], " +
                "[data-view-type='calendar'], " +
                "[data-view-type='list-form']");
            if (searchableView) {
                focusSearchAfterSwap = true;
                searchableView.click();
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

    function startDownloads(detail) {
        const urls = detail && detail.urls ? detail.urls : [];
        for (const url of urls) {
            const frame = document.createElement("iframe");
            frame.hidden = true;
            frame.src = url;
            frame.addEventListener("load", function () {
                window.setTimeout(() => frame.remove(), 1000);
            });
            document.body.append(frame);
        }
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
                ".vs-select-column, button, a, summary, details") ||
                (!allowFieldControls && event.target.closest(
                    "input, select, textarea, label, " +
                    "[contenteditable='true']"))) {
            return null;
        }
        return event.target.closest(".vs-row");
    }

    function markTreeRowSelected(row) {
        const tree = row.closest(".vs-table-wrap");
        if (!tree) {
            return;
        }
        for (const candidate of tree.querySelectorAll(".vs-row")) {
            const selected = candidate === row;
            candidate.classList.toggle("vs-row-current", selected);
            const checkbox = candidate.querySelector(
                ".vs-select-column input[aria-label='Select record']");
            if (checkbox) {
                checkbox.checked = selected;
            }
        }
        const selectAll = tree.querySelector(
            "thead input[aria-label='Select all records']");
        if (selectAll) {
            selectAll.checked = false;
        }
    }

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
        const search = event.target.closest("[data-search-autocomplete]");
        if (search) {
            updateSearchCompletion(search);
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

    document.addEventListener("focusin", function (event) {
        const search = event.target.closest("[data-search-autocomplete]");
        if (search) {
            updateSearchCompletion(search);
        }
    });

    document.addEventListener("click", function (event) {
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
        if (window.htmx) {
            window.htmx.ajax("POST", url, {
                target: "#workspace",
                swap: "outerHTML",
                pushUrl: true,
            });
        } else {
            const request = document.createElement("button");
            request.hidden = true;
            request.setAttribute("hx-post", url);
            request.setAttribute("hx-target", "#workspace");
            request.setAttribute("hx-swap", "outerHTML");
            request.setAttribute("hx-push-url", "true");
            document.body.append(request);
            fallbackRequest(request).finally(() => request.remove());
        }
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
                if (window.htmx) {
                    window.htmx.trigger(input, "htmx:abort");
                }
                const request = replaceRequests.get(input);
                if (request) {
                    request.abort();
                    replaceRequests.delete(input);
                }
                window.clearTimeout(fallbackTimers.get(input));
                fallbackTimers.delete(input);
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
            markTreeRowSelected(row);
            window.clearTimeout(rowClickTimer);
            rowClickTimer = window.setTimeout(function () {
                const selectAction = row.querySelector(
                    "[data-row-select-action]");
                if (selectAction) {
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
                fallbackRequest(form);
            }
            return;
        }
        const row = treeRowFromEvent(event, false);
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
        if (event.target.closest?.(
                "input, textarea, select, [contenteditable='true']")) {
            return;
        }
        const definition = shortcutDefinitions.find(
            item => matchesShortcut(event, item));
        if (!definition ||
                document.querySelector(".vs-modal-backdrop")) {
            return;
        }
        if (activateShortcut(definition.action)) {
            event.preventDefault();
        }
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
                ".vs-relation-option");
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
            const option = widget.querySelector(".vs-relation-option");
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
    document.addEventListener("click", function (event) {
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
    document.addEventListener("keydown", function (event) {
        const globalSearch = event.target.closest(
            "[data-global-search-input][data-global-search-assistant]");
        if (globalSearch && event.key === "Enter" &&
                !event.isComposing && !event.shiftKey &&
                !event.ctrlKey && !event.altKey && !event.metaKey) {
            const text = globalSearch.value.trim();
            if (!text) {
                return;
            }
            event.preventDefault();
            event.stopImmediatePropagation();
            if (window.htmx) {
                window.htmx.trigger(globalSearch, "htmx:abort");
            }
            const pending = replaceRequests.get(globalSearch);
            if (pending) {
                pending.abort();
                replaceRequests.delete(globalSearch);
            }
            window.clearTimeout(fallbackTimers.get(globalSearch));
            fallbackTimers.delete(globalSearch);
            globalSearch.value = "";
            globalSearch.closest("#global-search")?.querySelector(
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
                submit.click();
            };
            const help = document.querySelector(
                "[data-panel-option='help']");
            if (help?.getAttribute("aria-pressed") === "true") {
                send();
            } else if (help) {
                fallbackRequest(help).then(send);
            }
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
    document.addEventListener("htmx:afterSwap", function () {
        restoreFocus();
        initializeSearchCompletions();
        focusPendingSearch();
        scheduleInitialFormFocus();
        syncShellState();
        syncWorkspaceStickyOffsets();
        window.requestAnimationFrame(syncWorkspaceStickyOffsets);
        scheduleChatPolling();
        initializeHelp();
        scheduleNoticeDismissal();
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

    function formDataFor(element) {
        function addDeclaredValues(data) {
            const declared = element.getAttribute("hx-vals");
            if (!declared) {
                return data;
            }
            try {
                const values = JSON.parse(declared);
                for (const [name, value] of Object.entries(values)) {
                    data.set(name, value);
                }
            } catch (error) {
                // HTMX will ignore an invalid static hx-vals value too.
            }
            return data;
        }
        if (element instanceof HTMLFormElement) {
            return addDeclaredValues(new FormData(element));
        }
        const include = element.getAttribute("hx-include");
        if (include === "this" &&
                (element instanceof HTMLInputElement ||
                 element instanceof HTMLSelectElement ||
                 element instanceof HTMLTextAreaElement)) {
            const data = new FormData();
            if (element instanceof HTMLSelectElement && element.multiple) {
                for (const option of element.selectedOptions) {
                    data.append(element.name, option.value);
                }
            } else if (element.type !== "checkbox" || element.checked) {
                data.append(element.name, element.value);
            }
            return addDeclaredValues(data);
        }
        if (include === "closest form") {
            const form = element.closest("form");
            return addDeclaredValues(
                form ? new FormData(form) : new FormData());
        }
        if (include) {
            const data = new FormData();
            for (const control of document.querySelectorAll(include)) {
                if (!control.name || control.disabled ||
                        (control.type === "checkbox" && !control.checked)) {
                    continue;
                }
                data.append(control.name, control.value);
            }
            return addDeclaredValues(data);
        }
        const form = element.closest("form");
        return addDeclaredValues(
            form ? new FormData(form) : new FormData());
    }

    function replaceTarget(target, fragment, swap) {
        if (!target || swap === "none") {
            return null;
        }
        if (swap === "innerHTML") {
            target.replaceChildren(fragment);
            return target;
        } else {
            target.replaceWith(fragment);
            return fragment;
        }
    }

    function applyResponse(element, markup) {
        const template = document.createElement("template");
        template.innerHTML = markup.trim();
        const inserted = [];
        for (const outOfBand of template.content.querySelectorAll(
                "[hx-swap-oob]")) {
            const specification = outOfBand.getAttribute("hx-swap-oob");
            const parts = specification.split(":");
            const swap = parts[0] || "outerHTML";
            const selector = parts[1] || "#" + outOfBand.id;
            const target = document.querySelector(selector);
            outOfBand.removeAttribute("hx-swap-oob");
            inserted.push(replaceTarget(target, outOfBand, swap));
        }
        const selector = element.getAttribute("hx-target");
        const target = selector ? document.querySelector(selector) : element;
        const swap = element.getAttribute("hx-swap") || "innerHTML";
        const content = template.content;
        const active = document.activeElement;
        if (active?.id && active.matches("[hx-preserve]")) {
            const incoming = content.querySelector(
                "[hx-preserve][id=\"" +
                CSS.escape(active.id) + "\"]");
            if (incoming) {
                incoming.replaceWith(active);
            }
        }
        if (!content.childNodes.length) {
            if (swap === "innerHTML" && target) {
                target.replaceChildren();
            }
            for (const node of inserted) {
                if (window.htmx && node?.isConnected) {
                    window.htmx.process(node);
                }
            }
            return;
        }
        if (swap === "outerHTML") {
            inserted.push(replaceTarget(
                target, content.firstElementChild, swap));
        } else {
            inserted.push(replaceTarget(target, content, swap));
        }
        for (const node of inserted) {
            if (window.htmx && node?.isConnected) {
                window.htmx.process(node);
            }
        }
    }

    async function performFallbackRequest(element, signal) {
        const confirmation = element.getAttribute("hx-confirm");
        if (confirmation && !await requestConfirmation(confirmation)) {
            return;
        }
        rememberFocus();
        if (element.matches("[data-chat-form]") &&
                focusState.id === "message") {
            focusState.value = "";
            focusState.start = 0;
            focusState.end = 0;
        }
        const post = element.getAttribute("hx-post");
        const get = element.getAttribute("hx-get");
        const method = post ? "POST" : "GET";
        const url = post || get;
        if (!url) {
            return;
        }
        element.classList.add("htmx-request");
        try {
            const response = await fetch(url, {
                method: method,
                body: method === "POST" ? formDataFor(element) : undefined,
                credentials: "same-origin",
                signal: signal,
                headers: {
                    "HX-Request": "true",
                    "HX-Current-URL": window.location.href,
                },
            });
            if (!response.ok) {
                throw new Error(await response.text());
            }
            const redirectedURL = response.headers.get("HX-Redirect");
            if (redirectedURL) {
                window.location.assign(redirectedURL);
                return;
            }
            if (response.headers.get("HX-Refresh") === "true") {
                window.location.reload();
                return;
            }
            applyResponse(element, await response.text());
            syncShellState();
            syncWorkspaceStickyOffsets();
            window.requestAnimationFrame(syncWorkspaceStickyOffsets);
            scheduleChatPolling();
            initializeHelp();
            const pushedURL = response.headers.get("HX-Push-Url");
            if (pushedURL ||
                    element.getAttribute("hx-push-url") === "true") {
                history.pushState({}, "", pushedURL || url);
            }
            const trigger = response.headers.get("HX-Trigger");
            if (trigger) {
                try {
                    const events = JSON.parse(trigger);
                    startDownloads(events["voyager-download"]);
                } catch (error) {
                    // Non-JSON HX-Trigger values do not carry downloads.
                }
            }
            restoreFocus();
            initializeSearchCompletions();
            scheduleInitialFormFocus();
        } catch (error) {
            if (error.name === "AbortError") {
                return;
            }
            const host = document.getElementById("notifications");
            if (host) {
                const notice = document.createElement("div");
                notice.className = "vs-notice vs-notice-error";
                notice.textContent = error.message;
                host.replaceChildren(notice);
            }
        } finally {
            element.classList.remove("htmx-request");
        }
    }

    function fallbackRequest(element, replace) {
        if (replace) {
            const previous = replaceRequests.get(element);
            if (previous) {
                previous.abort();
            }
            const controller = new AbortController();
            replaceRequests.set(element, controller);
            return performFallbackRequest(element, controller.signal)
                .finally(function () {
                    if (replaceRequests.get(element) === controller) {
                        replaceRequests.delete(element);
                    }
                });
        }
        const owner = element.closest(".vs-screen, .vs-wizard") ||
            document.body;
        const previous = requestQueues.get(owner) || Promise.resolve();
        const current = previous
            .catch(function () {
                // A failed field update must not block later edits.
            })
            .then(() => performFallbackRequest(element));
        requestQueues.set(owner, current);
        return current;
    }

    function installFallback() {
        document.addEventListener("click", function (event) {
            const element = event.target.closest(
                "button[hx-post], button[hx-get], a[hx-post], a[hx-get]");
            if (!element) {
                return;
            }
            event.preventDefault();
            fallbackRequest(element);
        });
        document.addEventListener("submit", function (event) {
            const element = event.target.closest("form[hx-post], form[hx-get]");
            if (!element) {
                return;
            }
            event.preventDefault();
            fallbackRequest(element);
        });
        document.addEventListener("input", function (event) {
            const element = event.target.closest(
                "input[hx-post], textarea[hx-post]");
            if (!element) {
                return;
            }
            clearTimeout(fallbackTimers.get(element));
            fallbackTimers.set(element, setTimeout(
                () => fallbackRequest(element, true), 400));
        });
        document.addEventListener("change", function (event) {
            const element = event.target.closest(
                "input[hx-post], select[hx-post], textarea[hx-post]");
            if (element) {
                clearTimeout(fallbackTimers.get(element));
                fallbackTimers.delete(element);
                fallbackRequest(element, element.matches(
                    "input[type='text'], input[type='email'], " +
                    "input[type='url'], input[type='tel'], " +
                    "input[type='password'], textarea"));
            }
        });
    }

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
        const owner = action.closest(".vs-screen, .vs-wizard") ||
            document.getElementById(action.dataset.screenOwner || "");
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
        if (window.htmx) {
            window.htmx.config.historyCacheSize = 0;
        } else {
            installFallback();
        }
        syncShellState();
        syncWorkspaceStickyOffsets();
        window.requestAnimationFrame(syncWorkspaceStickyOffsets);
        scheduleChatPolling();
        initializeHelp();
        initializeSearchCompletions();
        scheduleInitialFormFocus();
    });
    window.addEventListener("load", syncWorkspaceStickyOffsets);
    window.addEventListener("resize", syncWorkspaceStickyOffsets);
    document.addEventListener(
        "scroll", scheduleWorkspaceStickyOffsets, true);
}());
