import type { components } from "./api.d.ts";

export type { components, operations, paths } from "./api.d.ts";

export type Schemas = components["schemas"];

export type MeResponse = Schemas["MeResponse"];
export type UserResponse = Schemas["UserResponse"];
export type ProviderResponse = Schemas["ProviderResponse"];
export type Limits = Schemas["Limits"];
export type DocumentOut = Schemas["DocumentOut"];
export type ChatOut = Schemas["ChatOut"];
export type MessageOut = Schemas["MessageOut"];
export type CitationOut = Schemas["CitationOut"];

export type LoginRequest = Schemas["LoginRequest"];
export type RegisterRequest = Schemas["RegisterRequest"];
export type UrlIn = Schemas["UrlIn"];
export type ChatCreate = Schemas["ChatCreate"];
export type MessageIn = Schemas["MessageIn"];

/** Body of every `AppError` response (`app/core/errors.py`). */
export type ApiErrorBody = { code: string; detail: string };

/** Body of a 422 from the `RequestValidationError` handler in `app/main.py`; no `input` or `ctx`. */
export type ValidationErrorBody = {
  detail: { type: string; loc: (string | number)[]; msg: string }[];
};

/** SSE events of `POST /chats/{id}/messages` (`stream_reply` in `app/services/chats.py`). */
export type ChatStreamEvent =
  | { event: "token"; data: { text: string } }
  | { event: "citations"; data: CitationOut[] }
  | { event: "done"; data: Record<string, never> }
  | { event: "error"; data: { code: "answer_failed"; detail: string } };
