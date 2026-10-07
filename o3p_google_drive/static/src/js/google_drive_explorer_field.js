/** @odoo-module **/

import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import {
    Component,
    onWillStart,
    onWillUpdateProps,
    proxy,
    t,
    useProps,
} from "@odoo/owl";

import { EXPLORER_VIEW_MODES, ExplorerNavigator } from "./explorer";

export class GoogleDriveExplorerField extends Component {
    static template = "o3p_google_drive.GoogleDriveExplorerField";

    props = useProps({
        ...standardFieldProps,
        height: t.string().optional("40vh"),
    });

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.navigator = null;
        this.pendingThumbnailIds = new Set();
        this.state = proxy({
            loading: true,
            folder: null,
            items: [],
            viewMode: EXPLORER_VIEW_MODES.DETAILS,
            contextItemId: false,
            canGoBack: false,
            isHome: true,
        });

        onWillStart(() => this.initialize(this._rootId(this.props)));
        onWillUpdateProps((nextProps) => {
            const nextRootId = this._rootId(nextProps);
            if (nextRootId !== this.rootId) {
                return this.initialize(nextRootId);
            }
        });
    }

    async initialize(rootId) {
        this.rootId = rootId || false;
        if (!rootId) {
            this.navigator = null;
            this.state.loading = false;
            this.state.folder = null;
            this.state.items = [];
            this._syncNavigationState();
            return;
        }
        this.navigator = new ExplorerNavigator(rootId);
        this._syncNavigationState();
        await this._loadFolder(rootId);
    }

    _rootId(props) {
        const field = props.record.fields[props.name];
        if (field.type === "many2one") {
            return props.record.data[props.name]?.id || false;
        }
        return props.record.resModel === "o3p.google.drive.item"
            ? props.record.resId
            : false;
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
            this._scheduleMissingThumbnails(payload.items);
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

    _scheduleMissingThumbnails(items) {
        const missingItems = items.filter(
            (item) =>
                !item.thumbnail_url &&
                (item.mime_type.startsWith("image/") ||
                    item.mime_type.startsWith("video/")) &&
                !this.pendingThumbnailIds.has(item.id)
        );
        if (!missingItems.length) {
            return;
        }

        for (const item of missingItems) {
            this.pendingThumbnailIds.add(item.id);
        }
        const missingIds = new Set(missingItems.map((item) => item.id));
        this.state.items = this.state.items.map((item) =>
            missingIds.has(item.id) ? { ...item, thumbnail_loading: true } : item
        );

        this.orm
            .call(
                "o3p.google.drive.item",
                "generate_explorer_thumbnails",
                [missingItems.map((item) => item.id)]
            )
            .then((generated) => {
                const thumbnailByItem = new Map(
                    generated.map((result) => [result.item_id, result.thumbnail_url])
                );
                this.state.items = this.state.items.map((item) =>
                    thumbnailByItem.has(item.id)
                        ? {
                              ...item,
                              thumbnail_url: thumbnailByItem.get(item.id),
                              thumbnail_loading: false,
                          }
                        : item
                );
            })
            .catch(() => {})
            .finally(() => {
                for (const itemId of missingIds) {
                    this.pendingThumbnailIds.delete(itemId);
                }
                this.state.items = this.state.items.map((item) =>
                    missingIds.has(item.id)
                        ? { ...item, thumbnail_loading: false }
                        : item
                );
            });
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

    get explorerStyle() {
        return `--o-o3p-drive-explorer-height: ${this.props.height};`;
    }
}

registry.category("fields").add("o3p_google_drive_explorer", {
    component: GoogleDriveExplorerField,
    additionalClasses: ["w-100"],
    supportedOptions: [
        {
            label: _t("Explorer height"),
            name: "height",
            type: "string",
            default: "40vh",
        },
    ],
    supportedTypes: ["char", "many2one"],
    extractProps: ({ options }) => ({
        height: options.height || "40vh",
    }),
});
