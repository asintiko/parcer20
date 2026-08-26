import React from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { ScanLine, X, ListChecks, Square } from 'lucide-react';
import { pluralRu } from '../../utils/plural';

interface BulkBarProps {
    /** Сколько сообщений доступно для выбора в текущем чате (для select-all) */
    total: number;
    selectedCount: number;
    processed: number;
    failed: number;
    inFlight: number;
    busy: boolean;
    onProcess: () => void;
    onCancel: () => void;
    onSelectAll: () => void;
    onDeselectAll: () => void;
}

const FORMS: [string, string, string] = ['сообщение', 'сообщения', 'сообщений'];

export const BulkBar: React.FC<BulkBarProps> = ({
    total,
    selectedCount,
    processed,
    failed,
    inFlight,
    busy,
    onProcess,
    onCancel,
    onSelectAll,
    onDeselectAll,
}) => {
    const allSelected = selectedCount > 0 && selectedCount === total;
    const word = pluralRu(selectedCount, FORMS);
    const progressDenominator = busy ? Math.max(processed + failed + inFlight, selectedCount) : selectedCount;
    const progress = progressDenominator > 0 ? (processed + failed) / progressDenominator : 0;

    return (
        <motion.div
            className="tg-bulk-bar"
            role="region"
            aria-label="Массовые действия"
            initial={{ y: -8, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            exit={{ y: -8, opacity: 0 }}
            transition={{ duration: 0.22, ease: [0.16, 1, 0.3, 1] }}
        >
            <button
                type="button"
                className="tg-bulk-cancel"
                onClick={onCancel}
                aria-label="Выйти из режима выбора"
                title="Esc"
            >
                <X size={16} />
            </button>

            <span className="tg-bulk-count" aria-live="polite">
                <strong>{selectedCount}</strong> {word}
            </span>

            <button
                type="button"
                className="tg-bulk-select-toggle"
                onClick={allSelected ? onDeselectAll : onSelectAll}
                disabled={total === 0}
                title={allSelected ? 'Снять выделение (⌘D)' : 'Выбрать все (⌘A)'}
            >
                <AnimatePresence mode="wait" initial={false}>
                    <motion.span
                        key={allSelected ? 'sq' : 'lc'}
                        initial={{ opacity: 0, scale: 0.7, rotate: -20 }}
                        animate={{ opacity: 1, scale: 1, rotate: 0 }}
                        exit={{ opacity: 0, scale: 0.7, rotate: 20 }}
                        transition={{ duration: 0.16, ease: [0.16, 1, 0.3, 1] }}
                        style={{ display: 'inline-flex' }}
                    >
                        {allSelected ? <Square size={13} /> : <ListChecks size={13} />}
                    </motion.span>
                </AnimatePresence>
                {allSelected ? 'Снять' : `Выбрать все · ${total}`}
            </button>

            <span className="tg-bulk-spacer" />

            <AnimatePresence initial={false}>
                {busy ? (
                    <motion.span
                        key="bulk-progress-label"
                        className="tg-bulk-progress-label"
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        exit={{ opacity: 0 }}
                    >
                        {processed} из {progressDenominator}
                        {failed > 0 ? ` · ошибок ${failed}` : ''}
                    </motion.span>
                ) : null}
            </AnimatePresence>

            <motion.button
                type="button"
                className="tg-bulk-action"
                onClick={onProcess}
                disabled={busy || selectedCount === 0}
                aria-busy={busy}
                whileTap={!busy && selectedCount > 0 ? { scale: 0.96 } : undefined}
            >
                <AnimatePresence mode="wait" initial={false}>
                    <motion.span
                        key={busy ? 'busy' : 'idle'}
                        initial={{ opacity: 0, scale: 0.7, rotate: -20 }}
                        animate={{ opacity: 1, scale: 1, rotate: 0 }}
                        exit={{ opacity: 0, scale: 0.7, rotate: 20 }}
                        transition={{ duration: 0.16, ease: [0.16, 1, 0.3, 1] }}
                        style={{ display: 'inline-flex' }}
                    >
                        {busy ? <ScanLine size={14} className="tg-msg-process-spin" /> : <ScanLine size={14} />}
                    </motion.span>
                </AnimatePresence>
                {busy ? 'Обработка…' : `В обработку · ${selectedCount}`}
            </motion.button>

            <div className="tg-bulk-progress" aria-hidden>
                <motion.div
                    className="tg-bulk-progress-fill"
                    initial={false}
                    animate={{ scaleX: progress }}
                    transition={{ type: 'spring', stiffness: 220, damping: 30 }}
                />
            </div>
        </motion.div>
    );
};
