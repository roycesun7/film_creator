const BASE = ''

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail || `API error ${res.status}`)
  }
  return res.json()
}

// Stats
export const fetchStats = () => request<Stats>('/api/stats')

// Media
export const fetchMedia = (params: { limit?: number; offset?: number; sort?: string; media_type?: string; date_from?: string; date_to?: string }) => {
  const q = new URLSearchParams()
  if (params.limit) q.set('limit', String(params.limit))
  if (params.offset) q.set('offset', String(params.offset))
  if (params.sort) q.set('sort', params.sort)
  if (params.media_type) q.set('media_type', params.media_type)
  if (params.date_from) q.set('date_from', params.date_from)
  if (params.date_to) q.set('date_to', params.date_to)
  return request<MediaListResponse>(`/api/media?${q}`)
}

export const fetchMediaDetail = (uuid: string) =>
  request<MediaItem>(`/api/media/${uuid}`)

export const deleteMediaItem = (uuid: string) =>
  request<{ deleted: boolean }>(`/api/media/${uuid}`, { method: 'DELETE' })

// Search
export const searchMedia = (body: SearchRequest) =>
  request<SearchResponse>('/api/search', { method: 'POST', body: JSON.stringify(body) })

// Index
export const startIndex = (body: IndexRequest) =>
  request<{ job_id: string }>('/api/index', { method: 'POST', body: JSON.stringify(body) })

// Preview
export const previewVideo = (body: PreviewRequest) =>
  request<EDLResponse>('/api/preview', { method: 'POST', body: JSON.stringify(body) })

// Generate
export const startGenerate = (body: GenerateRequest) =>
  request<{ job_id: string }>('/api/generate', { method: 'POST', body: JSON.stringify(body) })

// Jobs
export const fetchJob = (jobId: string) => request<Job>(`/api/jobs/${jobId}`)
export const fetchJobs = () => request<{ jobs: Job[] }>('/api/jobs')

// Videos
export const fetchVideos = () => request<{ videos: VideoFile[] }>('/api/videos')

export const deleteVideo = (filename: string) =>
  request<{ deleted: boolean; filename: string }>(`/api/videos/${encodeURIComponent(filename)}`, { method: 'DELETE' })

export const videoThumbnailUrl = (filename: string) =>
  `/api/videos/${encodeURIComponent(filename)}/thumbnail`

// Music upload
export async function uploadMusic(file: File): Promise<MusicUploadResponse> {
  const formData = new FormData()
  formData.append('file', file)
  const res = await fetch('/api/upload-music', { method: 'POST', body: formData })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail || `Music upload failed: ${res.status}`)
  }
  return res.json()
}

// Custom generate (user-reordered EDL)
export const startCustomGenerate = (body: CustomGenerateRequest) =>
  request<{ job_id: string }>('/api/generate-custom', { method: 'POST', body: JSON.stringify(body) })

// Upload
export async function uploadFiles(files: FileList | File[], describe = false): Promise<UploadResponse> {
  const formData = new FormData()
  for (const file of Array.from(files)) {
    formData.append('files', file)
  }
  const url = describe ? '/api/upload?describe=true' : '/api/upload'
  const res = await fetch(url, { method: 'POST', body: formData })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail || `Upload failed: ${res.status}`)
  }
  return res.json()
}

export interface UploadResponse {
  uploaded: number
  results: { filename: string; uuid?: string; media_type?: string; status?: string; error?: string }[]
}

// Thumbnail URL helper
export const thumbnailUrl = (uuid: string) => `/api/media/${uuid}/thumbnail`

// Video playback URL helper
export const videoUrl = (uuid: string) => `/api/media/${uuid}/video`

// Types
export interface Stats {
  total: number
  photos: number
  videos: number
  with_embeddings: number
  with_descriptions: number
  date_range: { earliest: string; latest: string } | null
  top_albums: { name: string; count: number }[]
  top_persons: { name: string; count: number }[]
  avg_quality: number | null
}

export interface MediaItem {
  uuid: string
  path: string
  media_type: string
  date: string | null
  lat: number | null
  lon: number | null
  albums: string[]
  labels: string[]
  persons: string[]
  width: number | null
  height: number | null
  duration: number | null
  description: Record<string, any>
  quality_score: number | null
  has_embedding?: boolean
}

export interface MediaListResponse {
  items: MediaItem[]
  total: number
  limit: number
  offset: number
}

export interface SearchRequest {
  query: string
  albums?: string[]
  persons?: string[]
  min_quality?: number
  date_from?: string
  date_to?: string
  limit?: number
  fast?: boolean
}

export interface SearchResponse {
  results: (MediaItem & { relevance_score?: number })[]
  count: number
  query: string
}

export interface IndexRequest {
  limit?: number
  album?: string
  after?: string
  before?: string
  describe?: boolean
  force?: boolean
}

export interface PreviewRequest {
  prompt: string
  duration?: number
  albums?: string[]
  persons?: string[]
  min_quality?: number
  num_candidates?: number
  uuids?: string[]
}

export interface GenerateRequest {
  prompt: string
  duration?: number
  theme?: string
  music?: string
  albums?: string[]
  persons?: string[]
  min_quality?: number
  num_candidates?: number
  uuids?: string[]
}

export interface EDLResponse {
  title: string
  narrative_summary: string
  music_mood: string
  estimated_duration: number
  shots: Shot[]
}

export interface Shot {
  uuid: string
  path: string
  media_type: string
  start_time: number
  end_time: number
  duration: number
  role: string
  reason: string
}

export interface Job {
  id: string
  type: string
  status: 'queued' | 'running' | 'completed' | 'failed'
  progress: number
  message: string
  created_at: number
  updated_at: number
  output_path?: string
  title?: string
}

export interface VideoFile {
  filename: string
  path: string
  size_mb: number
  created_at: string
}

export interface MusicUploadResponse {
  path: string
  filename: string
}

export interface ProjectMusicUploadResponse {
  music_path: string
  filename: string
  bpm?: number
  duration?: number
  sections?: number
}

export async function uploadProjectMusic(projectId: string, file: File): Promise<ProjectMusicUploadResponse> {
  const formData = new FormData()
  formData.append('file', file)
  const res = await fetch(`${BASE}/api/projects/${projectId}/music`, {
    method: 'POST',
    body: formData,
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail || `Music upload failed: ${res.status}`)
  }
  return res.json()
}

export async function deleteProjectMusic(projectId: string): Promise<void> {
  const res = await fetch(`${BASE}/api/projects/${projectId}/music`, {
    method: 'DELETE',
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail || `Failed to remove music: ${res.status}`)
  }
}

// ---------------------------------------------------------------------------
// Music Library (Jamendo)
// ---------------------------------------------------------------------------

export interface MusicTrack {
  id: string
  title: string
  artist: string
  duration: number
  bpm: number | null
  genre: string
  mood: string
  preview_url: string
  download_url: string
  license: string
  tags: string[]
  image_url: string
}

export interface MusicSearchResponse {
  tracks: MusicTrack[]
  count: number
}

export interface MusicSuggestResponse {
  tracks: MusicTrack[]
  count: number
  music_mood: string
}

export async function searchMusicLibrary(params: {
  query?: string
  mood?: string
  genre?: string
  min_duration?: number
  max_duration?: number
  limit?: number
}): Promise<MusicSearchResponse> {
  const q = new URLSearchParams()
  if (params.query) q.set('query', params.query)
  if (params.mood) q.set('mood', params.mood)
  if (params.genre) q.set('genre', params.genre)
  if (params.min_duration) q.set('min_duration', String(params.min_duration))
  if (params.max_duration) q.set('max_duration', String(params.max_duration))
  if (params.limit) q.set('limit', String(params.limit))
  return request<MusicSearchResponse>(`/api/music/search?${q}`)
}

export const fetchMusicLibraryStatus = () =>
  request<{ available: boolean }>('/api/music/status')

export async function selectLibraryMusic(
  projectId: string,
  trackId: string,
): Promise<ProjectMusicUploadResponse> {
  return request<ProjectMusicUploadResponse>(
    `/api/projects/${projectId}/music/library`,
    {
      method: 'POST',
      body: JSON.stringify({ track_id: trackId }),
    },
  )
}

export async function suggestMusic(
  projectId: string,
): Promise<MusicSuggestResponse> {
  return request<MusicSuggestResponse>(
    `/api/projects/${projectId}/music/suggest`,
  )
}

export interface CustomShotInput {
  uuid: string
  start_time: number
  end_time: number
  role: string
  reason: string
}

export interface CustomGenerateRequest {
  shots: CustomShotInput[]
  title: string
  theme: string
  music_path?: string
}

// ---------------------------------------------------------------------------
// Projects
// ---------------------------------------------------------------------------

export interface ClipEffect {
  type: string
  params: Record<string, any>
}

export interface ClipTransition {
  type: string
  duration: number
}

export interface TimelineClip {
  id: string
  media_uuid: string
  media_path: string
  media_type: string
  in_point: number
  out_point: number
  position: number
  duration: number
  volume: number
  effects: ClipEffect[]
  transition: ClipTransition
  role: string
  reason: string
}

export interface TextElement {
  id: string
  text: string
  position: number
  duration: number
  x: number
  y: number
  font_size: number
  font_family: string
  color: string
  bg_color: string
  animation: string
  style: string
}

export interface TimelineTrack {
  id: string
  name: string
  type: string
  clips: TimelineClip[]
  text_elements: TextElement[]
  muted: boolean
  locked: boolean
  volume: number
}

export interface Timeline {
  tracks: TimelineTrack[]
  duration: number
}

export interface RenderRecord {
  id: string
  output_path: string
  rendered_at: number
  theme: string
  resolution: string
  duration: number
}

export interface ProjectData {
  id: string
  name: string
  prompt: string
  created_at: number
  updated_at: number
  theme: string
  resolution: [number, number]
  fps: number
  music_path: string
  music_volume: number
  timeline: Timeline
  render_history: RenderRecord[]
  narrative_summary: string
  music_mood: string
}

export interface ProjectSummary {
  id: string
  name: string
  prompt: string
  theme: string
  created_at: number
  updated_at: number
  duration: number
  track_count: number
  render_count: number
}

export const fetchProjects = () =>
  request<{ projects: ProjectSummary[] }>('/api/projects')

export const createProject = (body: { name?: string; prompt?: string; theme?: string }) =>
  request<{ id: string; project: ProjectData }>('/api/projects', { method: 'POST', body: JSON.stringify(body) })

export const fetchProject = (id: string) =>
  request<ProjectData>(`/api/projects/${id}`)

export const updateProject = (id: string, project: ProjectData) =>
  request<ProjectData>(`/api/projects/${id}`, { method: 'PUT', body: JSON.stringify({ project }) })

export const deleteProjectApi = (id: string) =>
  request<{ deleted: boolean }>(`/api/projects/${id}`, { method: 'DELETE' })

export const projectPreview = (id: string) =>
  request<{ job_id: string }>(`/api/projects/${id}/preview`, { method: 'POST' })

export const projectRender = (id: string) =>
  request<{ job_id: string }>(`/api/projects/${id}/render`, { method: 'POST' })

export const projectMusicUrl = (id: string) =>
  `${BASE}/api/projects/${id}/music/file`
