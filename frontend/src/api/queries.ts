import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import type {
  Agent,
  AuditLog,
  Capabilities,
  Conversation,
  ConversationDetail,
  DashboardStats,
  EitaaAccount,
  LoginChallenge,
  Message,
  Note,
  Notification,
  Page,
} from "../types";

/* ---------------- conversations ---------------- */
export interface ConversationFilters {
  q?: string;
  status?: string[];
  read_state?: string;
  answer_state?: string;
  assigned?: string;
  account_id?: number;
  sort?: string;
  page?: number;
  page_size?: number;
}

export function useConversations(filters: ConversationFilters) {
  return useQuery({
    queryKey: ["conversations", filters],
    queryFn: () => {
      const params = new URLSearchParams();
      if (filters.q) params.set("q", filters.q);
      filters.status?.forEach((s) => params.append("status", s));
      if (filters.read_state) params.set("read_state", filters.read_state);
      if (filters.answer_state) params.set("answer_state", filters.answer_state);
      if (filters.assigned) params.set("assigned", filters.assigned);
      if (filters.account_id) params.set("account_id", String(filters.account_id));
      if (filters.sort) params.set("sort", filters.sort);
      params.set("page", String(filters.page ?? 1));
      params.set("page_size", String(filters.page_size ?? 30));
      return api<Page<Conversation>>(`/api/v1/conversations?${params.toString()}`);
    },
    placeholderData: (previous) => previous,
  });
}

export function useConversation(id: number | null) {
  return useQuery({
    queryKey: ["conversation", id],
    queryFn: () => api<ConversationDetail>(`/api/v1/conversations/${id}`),
    enabled: id !== null,
  });
}

export function useConversationAction(id: number) {
  const queryClient = useQueryClient();
  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["conversations"] });
    queryClient.invalidateQueries({ queryKey: ["conversation", id] });
  };
  return { invalidate };
}

export function useConversationActions() {
  const queryClient = useQueryClient();
  const invalidateAll = () => {
    queryClient.invalidateQueries({ queryKey: ["conversations"] });
    queryClient.invalidateQueries({ queryKey: ["conversation"] });
    queryClient.invalidateQueries({ queryKey: ["dashboard"] });
  };
  return { invalidateAll };
}

/* ---------------- messages ---------------- */
export function useMessages(conversationId: number | null) {
  return useQuery({
    queryKey: ["messages", conversationId],
    queryFn: () =>
      api<Page<Message>>(
        `/api/v1/conversations/${conversationId}/messages?page=1&page_size=200`,
      ),
    enabled: conversationId !== null,
  });
}

export function useSendMessage(conversationId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (payload: {
      text: string;
      replyTo?: number | null;
      file?: File | null;
      asVoice?: boolean;
      durationSeconds?: number;
    }) => {
      const formData = new FormData();
      formData.append("text", payload.text);
      if (payload.replyTo) formData.append("reply_to_message_id", String(payload.replyTo));
      if (payload.file) formData.append("file", payload.file);
      if (payload.asVoice) formData.append("as_voice", "true");
      if (payload.durationSeconds)
        formData.append("duration_seconds", String(payload.durationSeconds));
      return api<Message>(`/api/v1/conversations/${conversationId}/messages`, {
        method: "POST",
        formData,
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["messages", conversationId] });
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
      queryClient.invalidateQueries({ queryKey: ["conversation", conversationId] });
      queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
}

export function useRetryMessage() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (messageId: number) =>
      api<Message>(`/api/v1/messages/${messageId}/retry`, { method: "POST" }),
    onSuccess: (message: Message) => {
      queryClient.invalidateQueries({ queryKey: ["messages", message.conversation_id] });
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
    },
  });
}

/* ---------------- notes ---------------- */
export function useNotes(conversationId: number | null) {
  return useQuery({
    queryKey: ["notes", conversationId],
    queryFn: () => api<Note[]>(`/api/v1/conversations/${conversationId}/notes`),
    enabled: conversationId !== null,
  });
}

export function useAddNote(conversationId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: string) =>
      api<Note>(`/api/v1/conversations/${conversationId}/notes`, {
        method: "POST",
        body: { body },
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["notes", conversationId] }),
  });
}

/* ---------------- agents ---------------- */
export function useAgents() {
  return useQuery({
    queryKey: ["agents"],
    queryFn: () => api<Page<Agent>>("/api/v1/agents?page_size=100"),
  });
}

/* ---------------- eitaa accounts ---------------- */
export function useEitaaAccounts() {
  return useQuery({
    queryKey: ["eitaa-accounts"],
    queryFn: () => api<EitaaAccount[]>("/api/v1/eitaa/accounts"),
  });
}

export function useRequestCode() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (phoneNumber: string) =>
      api<LoginChallenge>("/api/v1/eitaa/accounts/request-code", {
        method: "POST",
        body: { phone_number: phoneNumber },
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["audit-logs"] }),
  });
}

export function useVerifyCode() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: { challenge_id: string; otp_code: string }) =>
      api<EitaaAccount>("/api/v1/eitaa/accounts/verify", { method: "POST", body: payload }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["eitaa-accounts"] }),
  });
}

/* ---------------- notifications ---------------- */
export function useNotifications(onlyUnread = false) {
  return useQuery({
    queryKey: ["notifications", onlyUnread],
    queryFn: () =>
      api<Page<Notification>>(
        `/api/v1/notifications?page_size=50${onlyUnread ? "&unread=true" : ""}`,
      ),
  });
}

export function useMarkAllRead() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => api("/api/v1/notifications/read-all", { method: "POST" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["notifications"] });
      queryClient.invalidateQueries({ queryKey: ["unread-count"] });
    },
  });
}

/* ---------------- dashboard & audit ---------------- */
export function useDashboard() {
  return useQuery({
    queryKey: ["dashboard"],
    queryFn: () => api<DashboardStats>("/api/v1/dashboard/stats"),
    refetchInterval: 30_000,
  });
}

export function useAuditLogs(filters: { action?: string; q?: string; page?: number }) {
  return useQuery({
    queryKey: ["audit-logs", filters],
    queryFn: () => {
      const params = new URLSearchParams();
      if (filters.action) params.set("action", filters.action);
      if (filters.q) params.set("q", filters.q);
      params.set("page", String(filters.page ?? 1));
      params.set("page_size", "50");
      return api<Page<AuditLog>>(`/api/v1/audit-logs?${params.toString()}`);
    },
    placeholderData: (previous) => previous,
  });
}

export function useCapabilities() {
  return useQuery({
    queryKey: ["capabilities"],
    queryFn: () => api<Capabilities>("/api/v1/capabilities"),
    staleTime: 10 * 60_000,
  });
}
