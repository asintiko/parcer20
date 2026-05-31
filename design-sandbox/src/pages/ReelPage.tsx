import React, { useEffect, useMemo, useState } from 'react';
import { motion, AnimatePresence, type Variants } from 'motion/react';
import {
    ArrowLeft,
    Bell,
    Menu,
    Plus,
    Search,
    Send,
    Sparkles,
    X,
} from 'lucide-react';
import '../styles/reel.css';

const SCENE_DURATION = 6800;
const TOTAL_SCENES = 7;

const scenes = [
    {
        id: 'opening',
        eyebrow: 'EDITORIAL · WORKSPACE',
        title: 'Тихая революция',
        sub: 'Не шум, не градиенты — типографика, ритм, бумага.',
    },
    {
        id: 'tokens',
        eyebrow: 'СЦЕНА · 01',
        title: 'Motion-токены',
        sub: 'От одной кривой на всё — к специализированным easing для каждого масштаба.',
    },
    {
        id: 'fab',
        eyebrow: 'СЦЕНА · 02',
        title: 'AI-агент: запуск',
        sub: 'Круглая кнопка превратилась в editorial-pill с типографикой.',
    },
    {
        id: 'panel',
        eyebrow: 'СЦЕНА · 03',
        title: 'Drawer: панель',
        sub: 'Плотный диалог с editorial-шрифтами и быстрыми сценариями.',
    },
    {
        id: 'navigation',
        eyebrow: 'СЦЕНА · 04',
        title: 'История диалогов',
        sub: 'Overlay-сайдбар → горизонтальная iOS-навигация. Один пейн, один transform.',
    },
    {
        id: 'reference',
        eyebrow: 'СЦЕНА · 05',
        title: 'Справочники',
        sub: 'TanStack Table, inline-редактирование, ⌘K shortcuts.',
    },
    {
        id: 'closing',
        eyebrow: 'FIN',
        title: 'Парсер · 2.0',
        sub: 'Editorial монохром. Тихая работа.',
    },
];

const fade: Variants = {
    hidden: { opacity: 0, y: 24 },
    visible: {
        opacity: 1,
        y: 0,
        transition: { duration: 0.7, ease: [0.16, 1, 0.3, 1] },
    },
    exit: {
        opacity: 0,
        y: -16,
        transition: { duration: 0.4, ease: [0.4, 0, 1, 1] },
    },
};

const eyebrowFade: Variants = {
    hidden: { opacity: 0, x: -12 },
    visible: { opacity: 1, x: 0, transition: { duration: 0.5, delay: 0.05, ease: [0.16, 1, 0.3, 1] } },
    exit: { opacity: 0, x: 8, transition: { duration: 0.3 } },
};

const subFade: Variants = {
    hidden: { opacity: 0, y: 12 },
    visible: { opacity: 1, y: 0, transition: { duration: 0.6, delay: 0.18, ease: [0.16, 1, 0.3, 1] } },
    exit: { opacity: 0, y: -8, transition: { duration: 0.3 } },
};

const stageVariants: Variants = {
    hidden: { opacity: 0, scale: 0.96 },
    visible: { opacity: 1, scale: 1, transition: { duration: 0.7, delay: 0.2, ease: [0.16, 1, 0.3, 1] } },
    exit: { opacity: 0, scale: 0.98, transition: { duration: 0.35, ease: [0.4, 0, 1, 1] } },
};

/* ────────── Stage components ────────── */

const TokensStage: React.FC = () => {
    const tokens = [
        { name: '--ease-standard', curve: 'cubic-bezier(.2,0,0,1)', label: 'micro · hover' },
        { name: '--ease-emphasized', curve: 'cubic-bezier(.3,0,0,1)', label: 'macro · drawer' },
        { name: '--ease-out', curve: 'cubic-bezier(.16,1,.3,1)', label: 'expo · slide' },
        { name: '--ease-pop', curve: 'cubic-bezier(.34,1.3,.64,1)', label: 'pop · badge' },
    ];
    return (
        <div className="rl-tokens">
            {tokens.map((t, i) => (
                <motion.div
                    key={t.name}
                    className="rl-token-row"
                    initial={{ opacity: 0, x: -24 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ duration: 0.5, delay: 0.32 + i * 0.12, ease: [0.16, 1, 0.3, 1] }}
                >
                    <div className="rl-token-name">{t.name}</div>
                    <div className="rl-token-label">{t.label}</div>
                    <div className="rl-token-curve">{t.curve}</div>
                </motion.div>
            ))}
        </div>
    );
};

const FabStage: React.FC = () => (
    <div className="rl-fab-stage">
        {/* BEFORE */}
        <motion.div
            className="rl-card"
            initial={{ opacity: 0, x: -40 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.6, delay: 0.32, ease: [0.16, 1, 0.3, 1] }}
        >
            <div className="rl-card-eyebrow">было</div>
            <div className="rl-card-canvas">
                <div className="rl-fab-old">
                    <Sparkles size={18} />
                </div>
            </div>
        </motion.div>
        <motion.div
            className="rl-arrow"
            initial={{ opacity: 0, scaleX: 0 }}
            animate={{ opacity: 1, scaleX: 1 }}
            transition={{ duration: 0.5, delay: 0.7, ease: [0.16, 1, 0.3, 1] }}
        />
        {/* AFTER */}
        <motion.div
            className="rl-card"
            initial={{ opacity: 0, x: 40 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.6, delay: 0.85, ease: [0.16, 1, 0.3, 1] }}
        >
            <div className="rl-card-eyebrow">стало</div>
            <div className="rl-card-canvas">
                <motion.div
                    className="rl-fab-new"
                    initial={{ scale: 0.8, opacity: 0 }}
                    animate={{ scale: 1, opacity: 1 }}
                    transition={{ duration: 0.5, delay: 1.05, ease: [0.34, 1.3, 0.64, 1] }}
                >
                    <span className="rl-fab-eyebrow">AI</span>
                    <span className="rl-fab-divider" />
                    <Sparkles size={14} />
                    <span className="rl-fab-label">Агент</span>
                </motion.div>
            </div>
        </motion.div>
    </div>
);

const PanelStage: React.FC = () => (
    <motion.div
        className="rl-panel-stage"
        initial={{ opacity: 0, y: 24 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6, delay: 0.3, ease: [0.16, 1, 0.3, 1] }}
    >
        <div className="rl-panel-frame">
            <div className="rl-panel-head">
                <div className="rl-panel-icon-btn"><Menu size={14} /></div>
                <div className="rl-panel-headline">
                    <div className="rl-panel-eyebrow"><Sparkles size={9} /> AI-агент</div>
                    <div className="rl-panel-title">Новый диалог</div>
                </div>
                <div className="rl-panel-actions">
                    <div className="rl-panel-icon-btn"><Plus size={14} /></div>
                    <div className="rl-panel-icon-btn"><Bell size={14} /></div>
                    <div className="rl-panel-icon-btn"><X size={14} /></div>
                </div>
            </div>
            <div className="rl-panel-body">
                <motion.div className="rl-panel-empty-eyebrow" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.7 }}>
                    AI · АГЕНТ
                </motion.div>
                <motion.h3 className="rl-panel-empty-title" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.85, duration: 0.6, ease: [0.16, 1, 0.3, 1] }}>
                    С чего начнём?
                </motion.h3>
                <div className="rl-panel-grid">
                    {['Сопоставление', 'Проверка', 'Сверка', 'Отчёт'].map((label, i) => (
                        <motion.div
                            key={label}
                            className="rl-panel-tile"
                            initial={{ opacity: 0, y: 20 }}
                            animate={{ opacity: 1, y: 0 }}
                            transition={{ delay: 1.1 + i * 0.08, duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
                        >
                            <div className="rl-panel-tile-num">0{i + 1}</div>
                            <div className="rl-panel-tile-name">{label}</div>
                        </motion.div>
                    ))}
                </div>
            </div>
            <div className="rl-panel-composer">
                <div className="rl-panel-input">Напишите запрос…</div>
                <motion.div
                    className="rl-panel-send"
                    initial={{ scale: 0.7, opacity: 0 }}
                    animate={{ scale: 1, opacity: 1 }}
                    transition={{ delay: 1.5, duration: 0.4, ease: [0.34, 1.3, 0.64, 1] }}
                >
                    <Send size={12} />
                </motion.div>
            </div>
        </div>
    </motion.div>
);

const NavigationStage: React.FC = () => {
    const [shifted, setShifted] = useState(false);
    useEffect(() => {
        const t1 = setTimeout(() => setShifted(true), 1800);
        const t2 = setTimeout(() => setShifted(false), 4400);
        return () => {
            clearTimeout(t1);
            clearTimeout(t2);
        };
    }, []);
    return (
        <motion.div
            className="rl-nav-stage"
            initial={{ opacity: 0, y: 24 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.3 }}
        >
            <div className="rl-nav-frame">
                <div className="rl-nav-head">
                    <motion.div
                        className="rl-panel-icon-btn"
                        animate={{ rotate: shifted ? 0 : 0 }}
                    >
                        <AnimatePresence mode="wait" initial={false}>
                            {shifted ? (
                                <motion.span key="back" initial={{ opacity: 0, x: 4 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -4 }} transition={{ duration: 0.18 }} style={{ display: 'inline-flex' }}>
                                    <ArrowLeft size={14} />
                                </motion.span>
                            ) : (
                                <motion.span key="menu" initial={{ opacity: 0, x: -4 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 4 }} transition={{ duration: 0.18 }} style={{ display: 'inline-flex' }}>
                                    <Menu size={14} />
                                </motion.span>
                            )}
                        </AnimatePresence>
                    </motion.div>
                    <div className="rl-panel-headline">
                        <AnimatePresence mode="wait" initial={false}>
                            <motion.div
                                key={shifted ? 'history' : 'chat'}
                                initial={{ opacity: 0, y: 6 }}
                                animate={{ opacity: 1, y: 0 }}
                                exit={{ opacity: 0, y: -4 }}
                                transition={{ duration: 0.22 }}
                            >
                                <div className="rl-panel-eyebrow"><Sparkles size={9} /> {shifted ? 'История' : 'AI-агент'}</div>
                                <div className="rl-panel-title">{shifted ? 'Диалоги · Активные' : 'Новый диалог'}</div>
                            </motion.div>
                        </AnimatePresence>
                    </div>
                </div>
                <div className="rl-nav-viewport">
                    <motion.div
                        className="rl-nav-track"
                        animate={{ x: shifted ? '-50%' : '0%' }}
                        transition={{ type: 'spring', stiffness: 380, damping: 38, mass: 0.9 }}
                    >
                        <div className="rl-nav-pane rl-nav-pane-chat">
                            <div className="rl-nav-empty">
                                <div className="rl-nav-empty-eye">AI · АГЕНТ</div>
                                <div className="rl-nav-empty-title">С чего начнём?</div>
                            </div>
                        </div>
                        <div className="rl-nav-pane rl-nav-pane-history">
                            <div className="rl-nav-search"><Search size={11} /> Поиск по диалогам</div>
                            {[1, 2, 3, 4].map((n) => (
                                <div key={n} className="rl-nav-thread">
                                    <div className="rl-nav-thread-title">Диалог · {n}</div>
                                    <div className="rl-nav-thread-meta">обновлён сегодня</div>
                                </div>
                            ))}
                        </div>
                    </motion.div>
                </div>
            </div>
            <div className="rl-nav-caption">
                <span className={shifted ? 'is-dim' : ''}>chat</span>
                <span className="rl-nav-arrow" />
                <span className={shifted ? '' : 'is-dim'}>history</span>
            </div>
        </motion.div>
    );
};

const ReferenceStage: React.FC = () => (
    <motion.div
        className="rl-ref-stage"
        initial={{ opacity: 0, y: 24 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6, delay: 0.3 }}
    >
        <div className="rl-ref-frame">
            <div className="rl-ref-head">
                <div>
                    <div className="rl-panel-eyebrow">Справочники</div>
                    <div className="rl-ref-title">Приложения</div>
                </div>
                <div className="rl-ref-shortcut"><kbd>⌘</kbd>+<kbd>K</kbd></div>
            </div>
            <div className="rl-ref-stats">
                {[
                    { l: 'всего', v: '124' },
                    { l: 'активных', v: '98' },
                    { l: 'архив', v: '14' },
                    { l: 'к проверке', v: '12' },
                ].map((s, i) => (
                    <motion.div
                        key={s.l}
                        className="rl-ref-stat"
                        initial={{ opacity: 0, y: 12 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ delay: 0.5 + i * 0.08, duration: 0.45, ease: [0.16, 1, 0.3, 1] }}
                    >
                        <div className="rl-ref-stat-num">{s.v}</div>
                        <div className="rl-ref-stat-label">{s.l}</div>
                    </motion.div>
                ))}
            </div>
            <div className="rl-ref-table">
                {['Click', 'Payme', 'Uzcard', 'Humo', 'Apelsin'].map((row, i) => (
                    <motion.div
                        key={row}
                        className="rl-ref-row"
                        initial={{ opacity: 0, x: -16 }}
                        animate={{ opacity: 1, x: 0 }}
                        transition={{ delay: 0.9 + i * 0.06, duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
                    >
                        <div className="rl-ref-row-name">{row}</div>
                        <div className="rl-ref-row-meta">P2P · активно</div>
                    </motion.div>
                ))}
            </div>
        </div>
    </motion.div>
);

const ClosingStage: React.FC = () => {
    const tags = ['EDITORIAL', 'INSTRUMENT SERIF', 'SQUARE RADII', 'MONOCHROME', 'SPRING MOTION'];
    return (
        <div className="rl-close">
            {tags.map((t, i) => (
                <motion.span
                    key={t}
                    className="rl-close-tag"
                    initial={{ opacity: 0, y: 18 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.5, delay: 0.4 + i * 0.1, ease: [0.16, 1, 0.3, 1] }}
                >
                    {t}
                </motion.span>
            ))}
        </div>
    );
};

const OpeningStage: React.FC = () => (
    <div className="rl-open">
        <motion.div
            className="rl-open-mark"
            initial={{ scale: 0.6, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            transition={{ duration: 0.8, delay: 0.3, ease: [0.16, 1, 0.3, 1] }}
        >
            ✦
        </motion.div>
    </div>
);

/* ────────── Composition ────────── */

const stageMap: Record<string, React.FC> = {
    opening: OpeningStage,
    tokens: TokensStage,
    fab: FabStage,
    panel: PanelStage,
    navigation: NavigationStage,
    reference: ReferenceStage,
    closing: ClosingStage,
};

export const ReelPage: React.FC = () => {
    const [sceneIndex, setSceneIndex] = useState(0);
    const scene = scenes[sceneIndex];
    const Stage = stageMap[scene.id];

    useEffect(() => {
        const t = setTimeout(() => {
            setSceneIndex((i) => (i + 1) % TOTAL_SCENES);
        }, SCENE_DURATION);
        return () => clearTimeout(t);
    }, [sceneIndex]);

    const progress = useMemo(() => ((sceneIndex + 1) / TOTAL_SCENES) * 100, [sceneIndex]);

    return (
        <div className="rl-root">
            <div className="rl-grid" aria-hidden />
            <header className="rl-header">
                <div className="rl-brand">PARCER · 2.0</div>
                <div className="rl-progress">
                    <div className="rl-progress-meta">
                        {String(sceneIndex + 1).padStart(2, '0')} / {String(TOTAL_SCENES).padStart(2, '0')}
                    </div>
                    <div className="rl-progress-bar">
                        <motion.div
                            className="rl-progress-fill"
                            animate={{ width: `${progress}%` }}
                            transition={{ duration: 0.6, ease: [0.16, 1, 0.3, 1] }}
                        />
                    </div>
                </div>
            </header>

            <main className="rl-main">
                <AnimatePresence mode="wait">
                    <motion.div key={scene.id} className="rl-scene">
                        <motion.div className="rl-eyebrow" variants={eyebrowFade} initial="hidden" animate="visible" exit="exit">
                            {scene.eyebrow}
                        </motion.div>
                        <motion.h1 className="rl-title" variants={fade} initial="hidden" animate="visible" exit="exit">
                            {scene.title}
                        </motion.h1>
                        <motion.p className="rl-sub" variants={subFade} initial="hidden" animate="visible" exit="exit">
                            {scene.sub}
                        </motion.p>
                        <motion.div className="rl-stage" variants={stageVariants} initial="hidden" animate="visible" exit="exit">
                            <Stage />
                        </motion.div>
                    </motion.div>
                </AnimatePresence>
            </main>

            <footer className="rl-footer">
                <span>EDITORIAL · MONOCHROME · 2026</span>
                <span className="rl-footer-dot" />
                <span>DESIGN SANDBOX</span>
            </footer>
        </div>
    );
};
