import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { chatCommandsApi, type ChatCommandCreate } from '../services/api';

export function useAiAgentCommands() {
    const queryClient = useQueryClient();

    const commandsQuery = useQuery({
        queryKey: ['agent-commands'],
        queryFn: chatCommandsApi.listCommands,
        staleTime: 30_000,
    });

    const invalidate = () => queryClient.invalidateQueries({ queryKey: ['agent-commands'] });

    const createMutation = useMutation({
        mutationFn: (payload: ChatCommandCreate) => chatCommandsApi.createCommand(payload),
        onSuccess: () => void invalidate(),
    });

    const updateMutation = useMutation({
        mutationFn: ({ id, data }: { id: string; data: Partial<ChatCommandCreate> }) =>
            chatCommandsApi.updateCommand(id, data),
        onSuccess: () => void invalidate(),
    });

    const deleteMutation = useMutation({
        mutationFn: (id: string) => chatCommandsApi.deleteCommand(id),
        onSuccess: () => void invalidate(),
    });

    return {
        commandsQuery,
        commands: commandsQuery.data || [],
        createMutation,
        updateMutation,
        deleteMutation,
    };
}
