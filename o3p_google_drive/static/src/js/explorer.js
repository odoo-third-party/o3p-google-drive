/** @odoo-module **/

export const EXPLORER_VIEW_MODES = Object.freeze({
    DETAILS: "details",
    ICONS: "icons",
});

export class ExplorerNavigator {
    constructor(rootId) {
        this.reset(rootId);
    }

    reset(rootId) {
        this.rootId = rootId;
        this.currentId = rootId;
        this.history = [];
    }

    enter(itemId) {
        if (!itemId || itemId === this.currentId) {
            return this.currentId;
        }
        this.history.push(this.currentId);
        this.currentId = itemId;
        return this.currentId;
    }

    back() {
        if (!this.history.length) {
            return this.currentId;
        }
        this.currentId = this.history.pop();
        return this.currentId;
    }

    home() {
        this.currentId = this.rootId;
        this.history = [];
        return this.currentId;
    }

    get canGoBack() {
        return this.history.length > 0;
    }

    get isHome() {
        return this.currentId === this.rootId;
    }
}
