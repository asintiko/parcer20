import React, { useEffect, useMemo, useRef, useState } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import {
    BarChart3,
    Calculator,
    FileText,
    Plus,
    RefreshCw,
    Search,
    Sparkles,
    Trash2,
    Wallet,
    Zap,
    type LucideIcon,
} from 'lucide-react';
import { useAiAgentCommands } from '../hooks/useAiAgentCommands';
import { useToast } from './Toast';
import { Dialog } from './motion/Dialog';
import type { ChatCommand } from '../services/api';

const ICON_BY_NAME: Record<string, LucideIcon> = {
    wallet: Wallet,
    'bar-chart-3': BarChart3,
    'bar-chart': BarChart3,
    'refresh-cw': RefreshCw,
    calculator: Calculator,
    'file-text': FileText,
    search: Search,
    zap: Zap,
    sparkles: Sparkles,
};

function iconByName(name?: string | null): LucideIcon {
    if (!name) return Sparkles;
    return ICON_BY_NAME[name.toLowerCase()] || Sparkles;
}

const paletteVariants = {
    hidden: { opacity: 0, y: 8, scale: 0.98 },
    visible: {
        opacity: 1,
        y: 0,
        scale: 1,
        transition: { duration: 0.18, ease: [0.2, 0, 0, 1] as [number, number, number, number] },
    },
    exit: {
        opacity: 0,
        y: 6,
        scale: 0.98,
        transition: { duration: 0.12, ease: [0.3, 0, 1, 1] as [number, number, number, number] },
    },
};

interface AiAgentCommandPaletteProps {
    open: boolean;
    onClose: () => void;
    onPick: (cmd: ChatCommand) => void;
    isAdmin: boolean;
    filter?: string;
}

export const AiAgentCommandPalette: React.FC<AiAgentCommandPaletteProps> = ({
    open,
    onClose,
    onPick,
    isAdmin,
    filter = '',
}) => {
    const { showToast } = useToast();
    const { commands, createMutation, deleteMutation } = useAiAgentCommands();
    const [search, setSearch] = useState('');
    const [highlight, setHighlight] = useState(0);
    const [createOpen, setCreateOpen] = useState(false);
    const searchRef = useRef<HTMLInputElement | null>(null);
    const listRef = useRef<HTMLDivElement | null>(null);

    const effectiveQuery = (filter || search).trim().toLowerCase();

    const filtered = useMemo(() => {
        const enabled = commands.filter((c) => c.enabled !== false);
        if (!effectiveQuery) return enabled;
        return enabled.filter((c) => c.title.toLowerCase().includes(effectiveQuery));
    }, [commands, effectiveQuery]);

    useEffect(() => {
        setHighlight(0);
    }, [effectiveQuery, open]);

    useEffect(() => {
        if (open && !filter) {
            const id = window.setTimeout(() => searchRef.current?.focus(), 20);
            return () => window.clearTimeout(id);
        }
    }, [open, filter]);

    useEffect(() => {
        if (!open) return;
        const onKey = (e: KeyboardEvent) => {
            if (e.key === 'Escape') {
                if (createOpen) return;
                e.preventDefault();
                onClose();
            } else if (e.key === 'ArrowDown') {
                e.preventDefault();
                setHighlight((h) => Math.min(filtered.length - 1, h + 1));
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                setHighlight((h) => Math.max(0, h - 1));
            } else if (e.key === 'Enter') {
                const cmd = filtered[highlight];
                if (cmd && !createOpen) {
                    e.preventDefault();
                    onPick(cmd);
                }
            }
        };
        window.addEventListener('keydown', onKey, true);
        return () => window.removeEventListener('keydown', onKey, true);
    }, [open, filtered, highlight, onClose, onPick, createOpen]);

    const submitCreate = async (payload: {
        title: string;
        icon: string;
        prompt_template: string;
        requested_tool: string;
        scope: 'team' | 'personal';
    }) => {
        try {
            await createMutation.mutateAsync({
                title: payload.title.trim(),
                prompt_template: payload.prompt_template.trim(),
                icon: payload.icon.trim() || null,
                requested_tool: payload.requested_tool.trim() || null,
                scope: payload.scope,
            });
            showToast('success', 'Команда создана');
            setCreateOpen(false);
        } catch (error: any) {
            showToast('error', 'Не удалось создать команду', { details: error?.message || String(error) });
        }
    };

    const handleDelete = async (id: string) => {
        try {
            await deleteMutation.mutateAsync(id);
        } catch (error: any) {
            showToast('error', 'Не удалось удалить команду', { details: error?.message || String(error) });
        }
    };

    return (
        <>
            <AnimatePresence>
                {open ? (
                    <>
                        <div className="agent-cmd-backdrop" onClick={onClose} aria-hidden />
                        <motion.div
                            className="agent-cmd"
                            role="dialog"
                            aria-label="Команды"
                            variants={paletteVariants}
                            initial="hidden"
                            animate="visible"
                            exit="exit"
                            onClick={(e) => e.stopPropagation()}
                        >
                            {!filter ? (
                                <div className="agent-cmd-search">
                                    <Search size={13} className="agent-cmd-search-icon" />
                                    <input
                                        ref={searchRef}
                                        type="text"
                                        className="agent-cmd-search-input"
                                        value={search}
                                        onChange={(e) => setSearch(e.target.value)}
                                        placeholder="Поиск команды"
                                    />
                                </div>
                            ) : null}
                            <div className="agent-cmd-list" ref={listRef}>
                                {filtered.length === 0 ? (
                                    <div className="agent-cmd-empty">
                                        {commands.length === 0 ? 'Команд пока нет' : 'Ничего не найдено'}
                                    </div>
                                ) : (
                                    filtered.map((cmd, i) => {
                                        const Icon = iconByName(cmd.icon);
                                        return (
                                            <div
                                                key={cmd.id}
                                                className={`agent-cmd-row${i === highlight ? ' is-active' : ''}`}
                                                onMouseEnter={() => setHighlight(i)}
                                            >
                                                <button
                                                    type="button"
                                                    className="agent-cmd-row-btn"
                                                    onClick={() => onPick(cmd)}
                                                >
                                                    <span className="agent-cmd-row-icon">
                                                        <Icon size={15} />
                                                    </span>
                                                    <span className="agent-cmd-row-title">{cmd.title}</span>
                                                </button>
                                                {isAdmin ? (
                                                    <button
                                                        type="button"
                                                        className="agent-cmd-row-del"
                                                        onClick={() => void handleDelete(cmd.id)}
                                                        aria-label="Удалить команду"
                                                        title="Удалить"
                                                    >
                                                        <Trash2 size={12} />
                                                    </button>
                                                ) : null}
                                            </div>
                                        );
                                    })
                                )}
                            </div>
                            {isAdmin ? (
                                <button
                                    type="button"
                                    className="agent-cmd-create"
                                    onClick={() => setCreateOpen(true)}
                                >
                                    <Plus size={13} />
                                    <span>Создать команду</span>
                                </button>
                            ) : null}
                        </motion.div>
                    </>
                ) : null}
            </AnimatePresence>

            <CommandCreateDialog
                open={createOpen}
                busy={createMutation.isPending}
                isAdmin={isAdmin}
                onClose={() => setCreateOpen(false)}
                onSubmit={submitCreate}
            />
        </>
    );
};

interface CommandCreateDialogProps {
    open: boolean;
    busy: boolean;
    isAdmin: boolean;
    onClose: () => void;
    onSubmit: (payload: {
        title: string;
        icon: string;
        prompt_template: string;
        requested_tool: string;
        scope: 'team' | 'personal';
    }) => void;
}

function CommandCreateDialog({ open, busy, isAdmin, onClose, onSubmit }: CommandCreateDialogProps) {
    const [title, setTitle] = useState('');
    const [icon, setIcon] = useState('');
    const [prompt, setPrompt] = useState('');
    const [tool, setTool] = useState('');
    const [scope, setScope] = useState<'team' | 'personal'>(isAdmin ? 'team' : 'personal');
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        if (open) {
            setTitle('');
            setIcon('');
            setPrompt('');
            setTool('');
            setScope(isAdmin ? 'team' : 'personal');
            setError(null);
        }
    }, [open, isAdmin]);

    const submit = () => {
        if (!title.trim() || !prompt.trim()) {
            setError('Название и текст команды обязательны');
            return;
        }
        setError(null);
        onSubmit({ title, icon, prompt_template: prompt, requested_tool: tool, scope });
    };

    return (
        <Dialog
            open={open}
            onClose={onClose}
            title="Новая команда"
            description="Шаблон запроса, который отправится агенту по клику."
            width={460}
            footer={
                <>
                    <span className="sp-spacer" />
                    <button type="button" className="agent-btn" onClick={onClose}>Отмена</button>
                    <button
                        type="button"
                        className="agent-btn agent-btn-primary"
                        onClick={submit}
                        disabled={busy || !title.trim() || !prompt.trim()}
                    >
                        {busy ? 'Создаю…' : 'Создать'}
                    </button>
                </>
            }
        >
            <div className="agent-cmd-form">
                <input className="agent-routines-input" value={title} autoFocus placeholder="Название (Кошелёк за неделю)"
                    onChange={(e) => setTitle(e.target.value)} />
                <input className="agent-routines-input" value={icon} placeholder="Иконка (wallet, bar-chart-3, zap…)"
                    onChange={(e) => setIcon(e.target.value)} />
                <textarea className="agent-routines-input" rows={3} value={prompt}
                    placeholder="Текст запроса агенту"
                    onChange={(e) => setPrompt(e.target.value)} />
                <input className="agent-routines-input agent-routines-input-mono" value={tool}
                    placeholder="Инструмент (необязательно)"
                    onChange={(e) => setTool(e.target.value)} />
                {isAdmin ? (
                    <select className="agent-routines-input" value={scope}
                        onChange={(e) => setScope(e.target.value as 'team' | 'personal')}>
                        <option value="team">Командная</option>
                        <option value="personal">Личная</option>
                    </select>
                ) : null}
                {error ? <div className="agent-routines-error">{error}</div> : null}
            </div>
        </Dialog>
    );
}
