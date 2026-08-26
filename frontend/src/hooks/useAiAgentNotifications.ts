import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { agentApi, type AgentNotification, type AgentReport, type AgentReportItem } from '../services/api';

export function useAiAgentNotifications() {
    const queryClient = useQueryClient();

    const notificationsQuery = useQuery({
        queryKey: ['agent-notifications'],
        queryFn: () => agentApi.listNotifications({ limit: 100 }),
        refetchInterval: 15_000,
        staleTime: 5_000,
    });

    const reportsQuery = useQuery({
        queryKey: ['agent-reports'],
        queryFn: () => agentApi.listReports({ include_team: true, limit: 50 }),
        refetchInterval: 30_000,
        staleTime: 10_000,
    });

    const patchNotifications = (mutate: (item: AgentNotification) => AgentNotification) => {
        queryClient.setQueryData<AgentNotification[]>(['agent-notifications'], (prev) =>
            prev ? prev.map(mutate) : prev,
        );
    };

    const patchReportItem = (updated: AgentReportItem) => {
        queryClient.setQueryData<AgentReport[]>(['agent-reports'], (prev) =>
            prev
                ? prev.map((report) =>
                      report.id === updated.report_id
                          ? {
                                ...report,
                                items: report.items.map((item) =>
                                    item.id === updated.id ? updated : item,
                                ),
                            }
                          : report,
                  )
                : prev,
        );
    };

    const readMutation = useMutation({
        mutationFn: (notificationId: string) => agentApi.readNotification(notificationId),
        onSuccess: (updated) => patchNotifications((item) => (item.id === updated.id ? updated : item)),
    });

    const readAllMutation = useMutation({
        mutationFn: () => agentApi.readAllNotifications(),
        onSuccess: () =>
            patchNotifications((item) =>
                item.is_read ? item : { ...item, is_read: true, read_at: new Date().toISOString() },
            ),
    });

    const claimMutation = useMutation({
        mutationFn: (itemId: string) => agentApi.claimReportItem(itemId),
        onSuccess: (updated) => patchReportItem(updated),
    });

    const releaseMutation = useMutation({
        mutationFn: (itemId: string) => agentApi.releaseReportItem(itemId),
        onSuccess: (updated) => patchReportItem(updated),
    });

    return {
        notificationsQuery,
        reportsQuery,
        readMutation,
        readAllMutation,
        claimMutation,
        releaseMutation,
        notifications: notificationsQuery.data || [],
        reports: reportsQuery.data || [],
        unreadCount: (notificationsQuery.data || []).filter((item) => !item.is_read).length,
    };
}
