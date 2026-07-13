// Ambient types for the Electron <webview> tag used by MiniAppHost, plus the
// electronAPI.miniApp bridge surface exposed by electron/preload.cjs.
//
// React's JSX.IntrinsicElements has no <webview>; without this the host TSX would
// not type-check under strict mode. Picked up ambiently via tsconfig `include: src`.

import type { DetailedHTMLProps, DOMAttributes, Ref, CSSProperties } from 'react';

interface WebviewHTMLAttributes<T> extends DOMAttributes<T> {
    src?: string;
    preload?: string;
    partition?: string;
    allowpopups?: boolean;
    disablewebsecurity?: boolean;
    useragent?: string;
    nodeintegration?: boolean;
    webpreferences?: string;
    style?: CSSProperties;
    className?: string;
    ref?: Ref<HTMLElement>;
}

declare global {
    namespace JSX {
        interface IntrinsicElements {
            webview: DetailedHTMLProps<WebviewHTMLAttributes<HTMLElement>, HTMLElement>;
        }
    }

    interface Window {
        electronAPI?: {
            platform?: string;
            isElectron?: boolean;
            miniApp?: {
                getPreloadPath: () => Promise<string>;
                openExternal: (url: string) => Promise<boolean>;
            };
            [key: string]: unknown;
        };
    }
}

export {};
