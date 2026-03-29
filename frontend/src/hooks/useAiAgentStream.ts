import { useEffect } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { API_BASE_URL, buildAuthorizedRequestHeaders } from '../services/api';

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

    useEffect(() => {
        if (!threadId || !enabled) {
            return;
        }

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
                        try {
                            JSON.parse(parsed.data);
                        } catch {
                            continue;
                        }
                        if (parsed.event === 'message' || parsed.event === 'run' || parsed.event === 'run_event') {
                            void queryClient.invalidateQueries({ queryKey: ['agent-thread', threadId] });
                            void queryClient.invalidateQueries({ queryKey: ['agent-threads'] });
                            void queryClient.invalidateQueries({ queryKey: ['agent-launcher-state'] });
                            void queryClient.invalidateQueries({ queryKey: ['agent-notifications'] });
                            void queryClient.invalidateQueries({ queryKey: ['agent-reports'] });
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
        };
    }, [enabled, queryClient, threadId]);
}
