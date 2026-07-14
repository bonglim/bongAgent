/**
 * LLM 모델 선택기에서 사용하는 보정 helper 모듈.
 *
 * 백엔드 설정을 정상적으로 불러오지 못했거나 저장된 선택값이 현재 모델 목록에
 * 없을 때, 프론트엔드가 항상 유효한 모델 id를 들고 있도록 fallback을 제공한다.
 */
export const FALLBACK_LLM_MODELS = [
  { id: "gemini-2.5-flash", label: "gemini-2.5-flash" },
  { id: "gemini-3.5-flash", label: "gemini-3.5-flash" },
  { id: "gpt5.5", label: "gpt5.5" },
  { id: "gpt-4o-mini", label: "GPT4o-mini" },
];

export const DEFAULT_LLM_MODEL = "gemini-3.5-flash";

/**
 * 백엔드 모델 설정 응답을 UI state에 바로 넣을 수 있는 형태로 정규화한다.
 *
 * @param {object | undefined} payload - ``/api/llm/models`` 응답 payload.
 * @returns {{models: Array<{id: string, label: string}>, defaultModel: string}}
 * @example
 * normalizeLlmModels(undefined); // 내장 fallback 모델 목록과 기본 모델 반환
 */
export function normalizeLlmModels(payload) {
  const models = Array.isArray(payload?.models) ? payload.models.filter((model) => model?.id && model?.label) : [];
  const safeModels = models.length ? models : FALLBACK_LLM_MODELS;
  const ids = new Set(safeModels.map((model) => model.id));
  const defaultModel = ids.has(payload?.default_model) ? payload.default_model : safeModels[0].id;
  return { models: safeModels, defaultModel };
}

/**
 * 선택 모델이 현재 모델 목록에 없으면 안전한 기본 모델로 보정한다.
 *
 * @param {string | undefined} model - 사용자가 선택했거나 저장된 모델 id.
 * @param {Array<{id: string}>} models - 현재 선택 가능한 모델 목록.
 * @returns {string} 실제 select 값으로 사용할 모델 id.
 * @example
 * normalizeLlmModel("unknown", [{ id: "demo" }]); // "demo"
 */
export function normalizeLlmModel(model, models = FALLBACK_LLM_MODELS) {
  const ids = new Set(models.map((item) => item.id));
  return ids.has(model) ? model : models[0]?.id || DEFAULT_LLM_MODEL;
}

/**
 * select 변경 이벤트에서 유효한 모델만 state에 저장하는 handler를 만든다.
 *
 * @param {(model: string) => void} setSelectedModel - React state setter.
 * @param {Array<{id: string}>} models - 현재 선택 가능한 모델 목록.
 * @returns {(event: Event) => void} select onChange handler.
 */
export function createLlmModelChangeHandler(setSelectedModel, models) {
  return (event) => {
    setSelectedModel(normalizeLlmModel(event.target.value, models));
  };
}
