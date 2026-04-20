import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { agentApi, type AgentThread } from '../services/api';

type ThreadView = 'active' | 'archived' | 'trash';

interface UseAiAgentSessionOptions {
    view?: ThreadView;
    search?: string;
}

export function useAiAgentSession(
    activeThreadId: string | null,
    setActiveThreadId: (threadId: string | null) => void,
    options: UseAiAgentSessionOptions = {},
) {
    const queryClient = useQueryClient();
    const view = options.view || 'active';
    const search = options.search?.trim() || '';

    const invalidateThreads = async () => {
        await Promise.all([
            queryClient.invalidateQueries({ queryKey: ['agent-threads'] }),
            queryClient.invalidateQueries({ queryKey: ['agent-launcher-state'] }),
            queryClient.invalidateQueries({ queryKey: ['agent-thread', activeThreadId] }),
        ]);
    };

    const threadsQuery = useQuery({
        queryKey: ['agent-threads', view, search],
        queryFn: () => agentApi.listThreads({ view, search: search || undefined }),
        staleTime: 15_000,
    });

    const threadQuery = useQuery({
        queryKey: ['agent-thread', activeThreadId],
        queryFn: () => agentApi.getThread(activeThreadId!),
        enabled: Boolean(activeThreadId),
        staleTime: 2_000,
    });

    const createThreadMutation = useMutation({
        mutationFn: (payload?: { title?: string; context?: Record<string, any> }) => agentApi.createThread(payload),
        onSuccess: (thread) => {
            setActiveThreadId(thread.id);
            void queryClient.invalidateQueries({ queryKey: ['agent-threads'] });
            void queryClient.invalidateQueries({ queryKey: ['agent-launcher-state'] });
            queryClient.setQueryData(['agent-thread', thread.id], {
                ...thread,
                messages: [],
                runs: [],
                run_events: [],
            });
        },
    });

    const sendMessageMutation = useMutation({
        mutationFn: async (payload: { threadId?: string | null; text: string; requestedTool?: string | null; metadata?: Record<string, any> }) => {
            let threadId = payload.threadId || activeThreadId;
            if (!threadId) {
                const created = await agentApi.createThread({
                    title: payload.text.slice(0, 80) || 'Новый диалог',
                });
                threadId = created.id;
                setActiveThreadId(threadId);
                void queryClient.invalidateQueries({ queryKey: ['agent-threads'] });
                void queryClient.invalidateQueries({ queryKey: ['agent-launcher-state'] });
            }
            const response = await agentApi.sendMessage(threadId, {
                text: payload.text,
                requested_tool: payload.requestedTool || undefined,
                metadata: payload.metadata,
            });
            return { ...response, threadId };
        },
        onSuccess: async (result) => {
            if (result.threadId) {
                setActiveThreadId(result.threadId);
                await Promise.all([
                    queryClient.invalidateQueries({ queryKey: ['agent-threads'] }),
                    queryClient.invalidateQueries({ queryKey: ['agent-thread', result.threadId] }),
                ]);
            }
        },
    });

    const renameThreadMutation = useMutation({
        mutationFn: ({ threadId, title }: { threadId: string; title: string }) => agentApi.updateThread(threadId, { title }),
        onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['agent-threads'] }),
    });

    const archiveThreadMutation = useMutation({
        mutationFn: (threadId: string) => agentApi.archiveThread(threadId),
        onSuccess: async (thread) => {
            if (activeThreadId === thread.id) {
                setActiveThreadId(null);
            }
            await invalidateThreads();
        },
    });

    const trashThreadMutation = useMutation({
        mutationFn: (threadId: string) => agentApi.trashThread(threadId),
        onSuccess: async (thread) => {
            if (activeThreadId === thread.id) {
                setActiveThreadId(null);
            }
            await invalidateThreads();
        },
    });

    const restoreThreadMutation = useMutation({
        mutationFn: (threadId: string) => agentApi.restoreThread(threadId),
        onSuccess: async () => {
            await invalidateThreads();
        },
    });

    const purgeThreadMutation = useMutation({
        mutationFn: (threadId: string) => agentApi.purgeThread(threadId),
        onSuccess: async (_result, threadId) => {
            if (activeThreadId === threadId) {
                setActiveThreadId(null);
            }
            await invalidateThreads();
        },
    });

    const createThread = async (payload?: { title?: string; context?: Record<string, any> }): Promise<AgentThread> => {
        return await createThreadMutation.mutateAsync(payload);
    };

    const sendMessage = async (payload: { text: string; requestedTool?: string | null; metadata?: Record<string, any> }) => {
        return await sendMessageMutation.mutateAsync(payload);
    };

    return {
        threadsQuery,
        threadQuery,
        createThreadMutation,
        sendMessageMutation,
        renameThreadMutation,
        archiveThreadMutation,
        trashThreadMutation,
        restoreThreadMutation,
        purgeThreadMutation,
        createThread,
        sendMessage,
        activeThread: threadQuery.data || null,
        threads: threadsQuery.data || [],
        messages: threadQuery.data?.messages || [],
        runs: threadQuery.data?.runs || [],
        runEvents: threadQuery.data?.run_events || [],
    };
}
