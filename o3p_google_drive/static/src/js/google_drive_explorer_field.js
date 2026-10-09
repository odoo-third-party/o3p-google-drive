/** @odoo-module **/

import { registry } from "@web/core/registry";
import { browser } from "@web/core/browser/browser";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import {
    Component,
    onPatched,
    onWillStart,
    onWillUpdateProps,
    proxy,
    signal,
    t,
    useProps,
} from "@odoo/owl";

import { EXPLORER_VIEW_MODES, ExplorerNavigator } from "./explorer";

export class GoogleDriveExplorerField extends Component {
    static template = "o3p_google_drive.GoogleDriveExplorerField";

    explorerRef = signal.ref();

    props = useProps({
        ...standardFieldProps,
        height: t.string().optional("40vh"),
        contactImageAction: t.string().optional(),
    });

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.notification = useService("notification");
        this.navigator = null;
        this.pendingThumbnailIds = new Set();
        this.attemptedEmptyFolderRefreshIds = new Set();
        this.revealBottomAfterExpansion = false;
        this.state = proxy({
            loading: true,
            refreshing: false,
            folder: null,
            items: [],
            viewMode: EXPLORER_VIEW_MODES.ICONS,
            contextItemId: false,
            canGoBack: false,
            isHome: true,
            isExpanded: false,
            settingContactImageItemId: false,
        });

        onWillStart(() => this.initialize(this._rootId(this.props)));
        onWillUpdateProps((nextProps) => {
            const nextRootId = this._rootId(nextProps);
            if (nextRootId !== this.rootId) {
                return this.initialize(nextRootId);
            }
        });
        onPatched(() => this._revealExpandedBottom());
    }

    async initialize(rootId) {
        this.rootId = rootId || false;
        this.attemptedEmptyFolderRefreshIds.clear();
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
            if (
                !payload.items.length &&
                !this.attemptedEmptyFolderRefreshIds.has(folderId)
            ) {
                this.attemptedEmptyFolderRefreshIds.add(folderId);
                await this.orm.call(
                    "o3p.google.drive.item",
                    "refresh_explorer_folder",
                    [folderId]
                );
                const refreshedPayload = await this.orm.call(
                    "o3p.google.drive.item",
                    "get_explorer_folder",
                    [folderId]
                );
                this.state.folder = refreshedPayload.folder;
                this.state.items = refreshedPayload.items;
                this._scheduleMissingThumbnails(refreshedPayload.items);
                return true;
            }
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
        if (!item || !item.is_folder || this.state.loading || this.state.refreshing) {
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
        if (!this.navigator?.canGoBack || this.state.loading || this.state.refreshing) {
            return;
        }
        const targetId = this.navigator.back();
        this._syncNavigationState();
        await this._loadFolder(targetId);
    }

    async onHome() {
        if (
            !this.navigator ||
            this.navigator.isHome ||
            this.state.loading ||
            this.state.refreshing
        ) {
            return;
        }
        const targetId = this.navigator.home();
        this._syncNavigationState();
        await this._loadFolder(targetId);
    }

    async onRefresh() {
        if (!this.navigator || this.state.loading || this.state.refreshing) {
            return;
        }
        const folderId = this.navigator.currentId;
        this.state.refreshing = true;
        this.state.contextItemId = false;
        try {
            const payload = await this.orm.call(
                "o3p.google.drive.item",
                "refresh_explorer_folder",
                [folderId]
            );
            if (this.navigator?.currentId !== folderId) {
                return;
            }
            this.state.folder = payload.folder;
            this.state.items = payload.items;
            this.attemptedEmptyFolderRefreshIds.add(folderId);
            this._scheduleMissingThumbnails(payload.items);
        } catch (error) {
            this.notification.add(
                error.message || _t("Could not refresh this Google Drive folder."),
                { type: "danger" }
            );
        } finally {
            this.state.refreshing = false;
        }
    }

    onSetDetailsView() {
        this.state.viewMode = EXPLORER_VIEW_MODES.DETAILS;
        this.state.contextItemId = false;
    }

    onSetIconsView() {
        this.state.viewMode = EXPLORER_VIEW_MODES.ICONS;
        this.state.contextItemId = false;
    }

    onToggleHeight() {
        const isExpanding = !this.state.isExpanded;
        this.revealBottomAfterExpansion = isExpanding;
        this.state.isExpanded = isExpanding;
    }

    _revealExpandedBottom() {
        if (!this.revealBottomAfterExpansion) {
            return;
        }
        this.revealBottomAfterExpansion = false;
        const explorer = this.explorerRef();
        if (!explorer) {
            return;
        }

        let revealed = false;
        const reveal = () => {
            if (revealed) {
                return;
            }
            revealed = true;
            if (this.state.isExpanded && explorer.isConnected) {
                explorer.scrollIntoView({
                    behavior: "smooth",
                    block: "end",
                    inline: "nearest",
                });
            }
        };
        explorer.addEventListener("transitionend", reveal, { once: true });
        browser.setTimeout(reveal, 220);
    }

    onOpenCurrentInDrive() {
        this._openInGoogleDrive(this.state.folder?.web_view_link);
    }

    onOpenItemInDrive(event) {
        const item = this._itemFromEvent(event);
        this.state.contextItemId = false;
        this._openInGoogleDrive(item?.web_view_link);
    }

    async onRunAdditionalAction(event) {
        const item = this._itemFromEvent(event);
        const actionId = Number(event.currentTarget.dataset.actionId);
        if (!item || !actionId) {
            return;
        }
        this.state.contextItemId = false;
        try {
            const result = await this.orm.call(
                "o3p.google.drive.item",
                "run_explorer_item_action",
                [item.id, actionId]
            );
            if (result) {
                await this.actionService.doAction(result);
            }
        } catch (error) {
            this.notification.add(
                error.message || _t("Could not run the explorer item action."),
                { type: "danger" }
            );
        }
    }

    canSetContactImage(item) {
        return Boolean(
            this.props.contactImageAction &&
            this.props.record.resId &&
            item?.mime_type?.startsWith("image/")
        );
    }

    async onSetContactImage(event) {
        const item = this._itemFromEvent(event);
        if (!this.canSetContactImage(item) || this.state.settingContactImageItemId) {
            return;
        }
        this.state.contextItemId = false;
        this.state.settingContactImageItemId = item.id;
        try {
            await this.orm.call(
                this.props.record.resModel,
                this.props.contactImageAction,
                [[this.props.record.resId], item.id]
            );
            await this.props.record.load();
            this.notification.add(_t("Contact image updated."), { type: "success" });
        } catch (error) {
            this.notification.add(error.message || _t("Could not update the contact image."), {
                type: "danger",
            });
        } finally {
            this.state.settingContactImageItemId = false;
        }
    }

    _openInGoogleDrive(url) {
        if (url) {
            browser.open(url, "_blank");
        }
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
        {
            label: _t("Set contact image method"),
            name: "contact_image_action",
            type: "string",
        },
    ],
    supportedTypes: ["char", "many2one"],
    extractProps: ({ options }) => ({
        height: options.height || "40vh",
        contactImageAction: options.contact_image_action,
    }),
});
