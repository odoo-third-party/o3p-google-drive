/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import {
    Component,
    onWillStart,
    onWillUpdateProps,
    useProps,
    useState,
} from "@odoo/owl";

import { EXPLORER_VIEW_MODES, ExplorerNavigator } from "./explorer";

export class GoogleDriveExplorerField extends Component {
    static template = "o3p_google_drive.GoogleDriveExplorerField";

    props = useProps(standardFieldProps);

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.navigator = null;
        this.state = useState({
            loading: true,
            folder: null,
            items: [],
            viewMode: EXPLORER_VIEW_MODES.DETAILS,
            contextItemId: false,
            canGoBack: false,
            isHome: true,
        });

        onWillStart(() => this.initialize(this.props.record.resId));
        onWillUpdateProps((nextProps) => {
            if (nextProps.record.resId !== this.props.record.resId) {
                return this.initialize(nextProps.record.resId);
            }
        });
    }

    async initialize(rootId) {
        if (!rootId) {
            this.state.loading = false;
            this.state.folder = null;
            this.state.items = [];
            return;
        }
        this.navigator = new ExplorerNavigator(rootId);
        this._syncNavigationState();
        await this._loadFolder(rootId);
    }

    async _loadFolder(folderId) {
        this.state.loading = true;
        this.state.contextItemId = false;
        try {
            const payload = await this.orm.call(
                "o3p.google.drive.item",
                "get_explorer_folder",
                [folderId]
            );
            this.state.folder = payload.folder;
            this.state.items = payload.items;
            return true;
        } catch (error) {
            this.notification.add(error.message || "Could not load this Google Drive folder.", {
                type: "danger",
            });
            return false;
        } finally {
            this.state.loading = false;
        }
    }

    async onOpenItem(event) {
        const item = this._itemFromEvent(event);
        if (!item || !item.is_folder || this.state.loading) {
            return;
        }
        const previousId = this.navigator.currentId;
        this.navigator.enter(item.id);
        this._syncNavigationState();
        if (!(await this._loadFolder(item.id))) {
            this.navigator.currentId = previousId;
            this.navigator.history.pop();
            this._syncNavigationState();
        }
    }

    async onBack() {
        if (!this.navigator?.canGoBack || this.state.loading) {
            return;
        }
        const targetId = this.navigator.back();
        this._syncNavigationState();
        await this._loadFolder(targetId);
    }

    async onHome() {
        if (!this.navigator || this.navigator.isHome || this.state.loading) {
            return;
        }
        const targetId = this.navigator.home();
        this._syncNavigationState();
        await this._loadFolder(targetId);
    }

    onSetDetailsView() {
        this.state.viewMode = EXPLORER_VIEW_MODES.DETAILS;
        this.state.contextItemId = false;
    }

    onSetIconsView() {
        this.state.viewMode = EXPLORER_VIEW_MODES.ICONS;
        this.state.contextItemId = false;
    }

    onToggleContext(event) {
        const item = this._itemFromEvent(event);
        if (!item) {
            return;
        }
        this.state.contextItemId =
            this.state.contextItemId === item.id ? false : item.id;
    }

    _itemFromEvent(event) {
        const itemId = Number(event.currentTarget.dataset.itemId);
        return this.state.items.find((item) => item.id === itemId);
    }

    _syncNavigationState() {
        this.state.canGoBack = Boolean(this.navigator?.canGoBack);
        this.state.isHome = this.navigator?.isHome ?? true;
    }

    formatSize(bytes) {
        if (!bytes) {
            return "";
        }
        const units = ["B", "KB", "MB", "GB", "TB"];
        const unitIndex = Math.min(
            Math.floor(Math.log(bytes) / Math.log(1024)),
            units.length - 1
        );
        const value = bytes / 1024 ** unitIndex;
        return `${value.toFixed(unitIndex ? 1 : 0)} ${units[unitIndex]}`;
    }
}

registry.category("fields").add("o3p_google_drive_explorer", {
    component: GoogleDriveExplorerField,
    supportedTypes: ["char"],
});
