export type InteractionKind = 'feed' | 'pet' | 'play' | 'sleep' | 'wake' | 'sit' | 'resume';
export type TabKey = 'companion' | 'chat' | 'system' | 'settings';
export type ModelMode = 'small' | 'large' | 'direct' | string;
export type RequestedModelMode = 'gaming_gpu' | 'normal' | 'power' | 'dual';

export interface Credentials {
  version: 1;
  baseUrl: string;
  token: string;
}

export interface Health {
  ok: boolean;
  name: string;
  species: string;
  gender: string;
  languages: string[];
  online_search: boolean;
  intensive_search: boolean;
  attachments: boolean;
  adaptive_models: boolean;
  codex_bridge: boolean;
  eevee_companion: boolean;
  physical_interactions: boolean;
  privileged_actions: boolean;
  conversations?: boolean;
  cross_chat_memory?: boolean;
  game_streaming?: boolean;
  chat_storage_limit_gb?: number;
  version: string;
}

export interface PetVitals {
  hunger: number;
  happiness: number;
  energy: number;
  trust: number;
  curiosity: number;
  asleep: boolean;
  seated?: boolean;
  last_interaction: string;
  updated_at: string;
  mood: string;
}

export interface PetState extends PetVitals {
  name?: string;
  species?: string;
  gender?: string;
  owner_name?: string;
  supported_languages?: string[];
  online_search_enabled?: boolean;
  codex_bridge_enabled?: boolean;
  eevee_companion_enabled?: boolean;
  bed_enabled?: boolean;
  authorization_configured?: boolean;
  authorization_available?: boolean;
  action_password_required?: boolean;
  pc_command_enabled?: boolean;
}

export interface Source {
  title?: string;
  url: string;
  snippet?: string;
}

export interface ActionResult {
  success: boolean;
  action: string;
  message: string;
  data: Record<string, unknown> | null;
  requires_confirmation: boolean;
  requires_authorization: boolean;
  challenge_id: string | null;
  authorization_expires_at: string | null;
  authorization_summary: string | null;
  password_configured: boolean;
}

export interface ChatResponse {
  message: string;
  model: string | null;
  model_mode: ModelMode;
  conversation_id?: string;
  conversation?: Conversation;
  user_message?: ChatMessage;
  assistant_message?: ChatMessage;
  model_reason?: string;
  offline?: boolean;
  error?: string;
  requires_authorization?: boolean;
  challenge_id?: string;
  authorization_expires_at?: string;
  authorization_summary?: string;
  password_configured?: boolean;
  action_result?: ActionResult;
  action_results?: ActionResult[];
  sources?: Source[];
}

export interface AttachmentInfo {
  attachment_id: string;
  name: string;
  kind: 'image' | 'pdf' | 'text';
  media_type: string;
  size: number;
}

export interface StoredAttachment {
  id?: string;
  attachment_id?: string;
  message_id?: string;
  conversation_id?: string;
  name: string;
  kind: 'image' | 'pdf' | 'text' | 'screenshot' | string;
  media_type: string;
  size: number;
  stored_size?: number;
  created_at?: string;
}

export interface ChatMessageMetadata {
  sources?: Source[];
  model?: string | null;
  model_mode?: ModelMode;
  model_reason?: string;
  action_result?: ActionResult;
  action_results?: ActionResult[];
  screenshot_id?: string;
  screenshot_ids?: string[];
  offline?: boolean;
  error?: string;
  [key: string]: unknown;
}

export interface ChatMessage {
  id: string;
  conversation_id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  origin: string;
  client_message_id?: string | null;
  created_at: string;
  metadata: ChatMessageMetadata | null;
  attachments: StoredAttachment[];
}

export interface Conversation {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  last_message_id?: string | null;
  message_count: number;
  preview: string;
  last_message_preview?: string;
  pinned?: boolean;
  archived?: boolean;
  archived_at?: string | null;
  summary?: string;
  summary_through_message_id?: number | null;
  revision?: number;
  is_default?: boolean;
}

export interface ConversationStorage {
  quota_bytes?: number;
  used_bytes?: number;
  free_bytes?: number;
  available_bytes?: number;
  object_bytes?: number;
  database_bytes?: number;
  min_free_bytes?: number;
  object_count?: number;
  attachment_count?: number;
  writable?: boolean;
  [key: string]: unknown;
}

export interface ConversationListResponse {
  conversations: Conversation[];
  next_cursor?: string | null;
  storage?: ConversationStorage;
}

export interface ConversationMessagesResponse {
  conversation: Conversation;
  messages: ChatMessage[];
  has_more: boolean;
  next_before_id: string | null;
}

export interface DeleteConversationResponse {
  ok?: boolean;
  deleted_id?: string;
  conversation_id?: string;
  replacement?: Conversation | null;
}

export interface PendingAttachment {
  id: string;
  uri: string;
  name: string;
  mimeType: string;
  size: number;
}

export interface ChatEntry {
  id: string;
  role: 'user' | 'assistant' | 'system';
  text: string;
  attachmentNames?: string[];
  sources?: Source[];
  model?: string | null;
  modelMode?: ModelMode;
  createdAt?: string;
  attachments?: StoredAttachment[];
  screenshotIds?: string[];
  clientMessageId?: string;
  delivery?: 'sending' | 'failed' | 'uncertain';
}

export interface GpuStatus {
  available?: boolean;
  total_gb?: number;
  free_gb?: number;
  effective_free_gb?: number;
}

export interface DetailedGpuStatus {
  index: number;
  uuid: string;
  name: string;
  role: string;
  total_gb?: number;
  used_gb?: number;
  free_gb?: number;
  utilization_percent?: number;
  temperature_c?: number;
  // Accepted for compatibility with prerelease/older telemetry payloads.
  total_vram_gb?: number;
  used_vram_gb?: number;
  free_vram_gb?: number;
  memory_total_mb?: number;
  memory_used_mb?: number;
  memory_free_mb?: number;
  driver_version?: string;
  pci_bus_id?: string;
  power_draw_w?: number;
  power_limit_w?: number;
  model?: string | null;
  status?: string;
  active?: boolean;
}

export interface ModelStatus {
  adaptive_enabled?: boolean;
  model?: string;
  model_mode?: 'small' | 'large' | 'power' | 'gaming_gpu' | 'dual';
  dual_model?: string;
  dual_model_installed?: boolean;
  dual_context_tokens?: number;
  dual_server_running?: boolean;
  dual_blocked_by_game?: boolean;
  dual_ai_limit_gb?: number;
  dual_gaming_limit_gb?: number;
  dual_last_error?: string;
  dual_warning?: string;
  dual_reasoning_effort?: string;
  pc_administrator?: boolean;
  dual_guard_interval_seconds?: number;
  dual_manual_unload_only?: boolean;
  action_password_required?: boolean;
  pc_command_enabled?: boolean;
  dual_loaded_models?: Array<{ name: string; vram_gb: number; gpu_percent: number }>;
  requested_mode?: RequestedModelMode;
  reason?: string;
  small_model?: string;
  small_model_installed?: boolean;
  large_model?: string;
  large_model_installed?: boolean;
  power_model?: string;
  power_model_installed?: boolean;
  power_context_tokens?: number;
  gaming_gpu_uuid?: string;
  gaming_gpu_model?: string;
  gaming_gpu_model_installed?: boolean;
  gaming_gpu_context_tokens?: number;
  gaming_gpu_server_url?: string;
  gaming_gpu_server_running?: boolean;
  gaming_gpu_server_owned?: boolean;
  gaming_gpu_blocked_by_game?: boolean;
  gaming_gpu_loaded_models?: Array<{
    name: string;
    vram_gb?: number;
    size_gb?: number;
    gpu_percent?: number;
  }>;
  switching?: boolean;
  switching_to?: RequestedModelMode | null;
  error?: string | null;
  vram_threshold_gb?: number;
  gpu?: GpuStatus;
  gpus?: DetailedGpuStatus[];
  game?: {
    active: boolean;
    processes: string[];
    error?: string | null;
  };
  loaded_models?: Array<{
    name: string;
    vram_gb?: number;
    size_gb?: number;
    gpu_percent?: number;
    gpu_index?: number;
    gpu_uuid?: string;
  }>;
}

export interface PcStatus {
  hostname?: string;
  system?:
    | string
    | {
        os_name?: string;
        os_version?: string;
        architecture?: string;
        hostname?: string;
        uptime_seconds?: number;
      };
  os_name?: string;
  os?: string;
  os_version?: string;
  uptime_seconds?: number;
  cpu_percent?: number;
  cpu_name?: string;
  cpu_cores?: number;
  cpu_physical_cores?: number;
  cpu_logical_cores?: number;
  cpu_frequency_mhz?: number;
  memory_percent?: number;
  memory_used_gb?: number;
  memory_total_gb?: number;
  memory_available_gb?: number;
  disk_percent?: number;
  disk_used_gb?: number;
  disk_free_gb?: number;
  disk_total_gb?: number;
  battery?: {
    percent: number;
    plugged: boolean;
  } | null;
  gpu?: {
    utilization_percent: number;
    memory_used_mb: number;
    memory_total_mb: number;
    temperature_c: number;
  } | null;
  gpus?: DetailedGpuStatus[];
}

export interface GameStreamingStatus {
  enabled: boolean;
  installed: boolean;
  service_status: string;
  running: boolean;
  ready: boolean;
  sunshine_ready: boolean;
  remote_ready: boolean;
  web_ready: boolean;
  ports: Record<string, boolean>;
  host: string;
  tailscale_ip: string;
  tailscale_ready: boolean;
  credentials_managed: boolean;
  credentials_verified: boolean;
  pin_submission_available: boolean;
  pairing_available: boolean;
  paired: boolean;
  paired_clients: number;
  paired_device_names: string[];
  gamepad_ready: boolean;
  capture_gpu: string;
  moonlight_app_store_url: string;
  wake_available: boolean;
  wake_reason: string;
  message?: string;
}
