import { useEffect, useRef } from 'react';
import { useQueryClient, type QueryKey } from '@tanstack/react-query';
import { API_BASE_URL, buildAuthorizedRequestHeaders } from '../services/api';

const INVALIDATE_DEBOUNCE_MS = 250;

const parseEventBlocks = (buffer: string) => {
    const blocks = buffer.split('\n\n');
    const complete = blocks.slice(0, -1);
    const remainder = blocks.length ? blocks[blocks.length - 1] : '';
    return { complete, remainder };
};

const parseBlock = (block: string): { event: string; data: string } | null => {
    const lines = block.split('\n');
    let event = 'message';
    const dataLines: string[] = [];
    for (const line of lines) {
        if (line.startsWith('event:')) {
            event = line.slice(6).trim();
        } else if (line.startsWith('data:')) {
            dataLines.push(line.slice(5).trim());
        }
    }
    if (!dataLines.length) return null;
    return { event, data: dataLines.join('\n') };
};

export function useAiAgentStream(threadId: string | null, enabled = true) {
    const queryClient = useQueryClient();
    const debounceTimersRef = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());

    useEffect(() => {
        if (!threadId || !enabled) {
            return;
        }

        const timers = debounceTimersRef.current;
        // Coalesce bursty SSE-triggered invalidations: many events can land in a
        // single read tick, so accumulate per-key and fire one invalidation each.
        const invalidate = (queryKey: QueryKey) => {
            const cacheKey = JSON.stringify(queryKey);
            const existing = timers.get(cacheKey);
            if (existing) clearTimeout(existing);
            timers.set(
                cacheKey,
                setTimeout(() => {
                    timers.delete(cacheKey);
                    void queryClient.invalidateQueries({ queryKey });
                }, INVALIDATE_DEBOUNCE_MS),
            );
        };

        const controller = new AbortController();
        let disposed = false;

        const run = async () => {
            try {
                const headers = await buildAuthorizedRequestHeaders({ Accept: 'text/event-stream' });
                delete headers['Content-Type'];
                const response = await fetch(`${API_BASE_URL}/api/agent/stream/${threadId}`, {
                    method: 'GET',
                    headers,
                    signal: controller.signal,
                    cache: 'no-store',
                });
                if (!response.ok || !response.body) {
                    return;
                }
                const reader = response.body.getReader();
                const decoder = new TextDecoder();
                let buffer = '';

                while (!disposed) {
                    const { done, value } = await reader.read();
                    if (done) break;
                    buffer += decoder.decode(value, { stream: true });
                    const { complete, remainder } = parseEventBlocks(buffer);
                    buffer = remainder;
                    for (const block of complete) {
                        const parsed = parseBlock(block);
                        if (!parsed || parsed.event === 'heartbeat') continue;
                        let payload: { status?: unknown } | null = null;
                        try {
                            payload = JSON.parse(parsed.data);
                        } catch {
                            continue;
                        }

                        if (
                            parsed.event === 'message' ||
                            parsed.event === 'run' ||
                            parsed.event === 'run_event'
                        ) {
                            // Conversation surface: always keep the open thread fresh.
                            invalidate(['agent-thread', threadId]);
                            invalidate(['agent-threads']);

                            // Reports are only produced on run completion — touch that
                            // cache exclusively on a terminal run event to avoid a
                            // full reports refetch on every streamed token.
                            if (
                                parsed.event === 'run' &&
                                String(payload?.status) === 'completed'
                            ) {
                                invalidate(['agent-reports']);
                            }
                        } else if (parsed.event === 'notification') {
                            invalidate(['agent-notifications']);
                        }
                    }
                }
            } catch (error: any) {
                if (error?.name !== 'AbortError') {
                    console.warn('agent stream disconnected', error);
                }
            }
        };

        void run();
        return () => {
            disposed = true;
            controller.abort();
            timers.forEach((timer) => clearTimeout(timer));
            timers.clear();
        };
    }, [enabled, queryClient, threadId]);
}
