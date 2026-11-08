import {
  MAX_VOUCHER_ATTACHMENT_BATCH_BYTES,
  MAX_VOUCHER_ATTACHMENT_COUNT,
  VoucherAttachmentClientError,
  assertVoucherAttachmentFile
} from "./voucherAttachmentClient.js";

export const AE_WEB_VOUCHER_ATTACHMENT_UI_SCHEMA_VERSION =
  "ae_web_voucher_attachment_ui.p8.v1";

const ACTIVE_ITEM_STATES = new Set(["QUEUED", "UPLOADING", "READY", "FAILED"]);

export function createVoucherAttachmentUiController({
  container,
  client,
  context,
  onSessionExpired = () => {}
}) {
  if (!container || typeof container.addEventListener !== "function") {
    throw new TypeError("Voucher attachment UI container is required.");
  }
  let currentClient = client;
  let requestContext = context;
  let state = createVoucherAttachmentUiState();
  let operationSequence = 0;
  let batchPromise = null;

  const render = () => {
    container.innerHTML = renderVoucherAttachmentUi(state, currentClient);
  };

  const expireIfNeeded = error => {
    if (error?.status === "SESSION_EXPIRED" || error?.httpStatus === 401) {
      onSessionExpired(error);
      return true;
    }
    return false;
  };

  const ensureBatch = async () => {
    if (state.batchId) return state.batchId;
    batchPromise ||= currentClient.createBatch(resolveContext(requestContext));
    try {
      const batch = await batchPromise;
      if (!state.batchId) {
        state = {
          ...state,
          batchId: batch.attachment_batch_id,
          phase: "UPLOADING",
          feedback: "첨부 묶음을 준비했습니다."
        };
        render();
      }
      return state.batchId;
    } finally {
      batchPromise = null;
    }
  };

  const uploadItem = async itemId => {
    const item = state.items.find(candidate => candidate.localId === itemId);
    if (!item || !["QUEUED", "FAILED"].includes(item.status) || state.locked) return;
    try {
      const batchId = await ensureBatch();
      state = updateItem(state, itemId, {
        status: "UPLOADING",
        progress: 30,
        error: null
      });
      state = { ...state, phase: "UPLOADING", feedback: `${item.name} 업로드 중` };
      render();
      const result = await currentClient.uploadItem(batchId, {
        attachmentId: item.attachmentId,
        file: item.file
      });
      state = updateItem(state, itemId, {
        status: "READY",
        progress: 100,
        error: null,
        serverItem: result.attachment
      });
      state = deriveReadyState(state);
      render();
    } catch (error) {
      if (expireIfNeeded(error)) return;
      state = updateItem(state, itemId, {
        status: "FAILED",
        progress: 0,
        error: attachmentErrorMessage(error)
      });
      state = {
        ...state,
        phase: "FAILED",
        feedback: `${item.name} 업로드에 실패했습니다.`
      };
      render();
    }
  };

  const addFiles = async files => {
    if (state.locked) return;
    const candidates = [...(files || [])];
    if (candidates.length === 0) return;
    const accepted = [];
    const errors = [];
    let projectedBytes = state.items.reduce((total, item) => total + item.size, 0);
    for (const file of candidates) {
      if (state.items.length + accepted.length >= MAX_VOUCHER_ATTACHMENT_COUNT) {
        errors.push("첨부 파일은 최대 20개까지 선택할 수 있습니다.");
        break;
      }
      try {
        assertVoucherAttachmentFile(file);
        if (projectedBytes + file.size > MAX_VOUCHER_ATTACHMENT_BATCH_BYTES) {
          throw new VoucherAttachmentClientError(
            "첨부 파일 전체 크기는 100MB를 넘을 수 없습니다.",
            { status: "VOUCHER_ATTACHMENT_BATCH_TOO_LARGE" }
          );
        }
        const duplicate = [...state.items, ...accepted].some(
          item => item.name === file.name && item.size === file.size
        );
        if (duplicate) {
          throw new VoucherAttachmentClientError("같은 이름과 크기의 파일이 이미 있습니다.", {
            status: "VOUCHER_ATTACHMENT_DUPLICATE_FILE"
          });
        }
        projectedBytes += file.size;
        accepted.push(localItem(file));
      } catch (error) {
        errors.push(attachmentErrorMessage(error));
      }
    }
    state = {
      ...state,
      phase: accepted.length > 0 ? "UPLOADING" : "FAILED",
      feedback:
        errors[0] || `${accepted.length}개 파일을 첨부 목록에 추가했습니다.`,
      items: [...state.items, ...accepted]
    };
    render();
    await Promise.all(accepted.map(item => uploadItem(item.localId)));
  };

  const removeItem = async itemId => {
    if (state.locked) return;
    const item = state.items.find(candidate => candidate.localId === itemId);
    if (!item) return;
    if (item.status === "UPLOADING") return;
    try {
      if (item.status === "READY" && state.batchId) {
        await currentClient.removeItem(state.batchId, item.attachmentId);
      }
      state = deriveReadyState({
        ...state,
        items: state.items.filter(candidate => candidate.localId !== itemId),
        feedback: `${item.name} 파일을 첨부 목록에서 제거했습니다.`
      });
      render();
    } catch (error) {
      if (expireIfNeeded(error)) return;
      state = {
        ...state,
        phase: "FAILED",
        feedback: attachmentErrorMessage(error)
      };
      render();
    }
  };

  const prepareForSubmission = async () => {
    if (state.items.length === 0) return null;
    if (state.locked && state.manifest) {
      const currentContext = resolveContext(requestContext);
      return currentContext.interactionId === state.manifest.interaction_id
        ? structuredClone(state.manifest)
        : null;
    }
    if (state.items.some(item => item.status !== "READY")) {
      throw new VoucherAttachmentClientError(
        "모든 첨부 파일이 READY 상태여야 전송할 수 있습니다.",
        { status: "VOUCHER_ATTACHMENT_NOT_READY" }
      );
    }
    const sequence = ++operationSequence;
    state = {
      ...state,
      phase: "SUBMITTING",
      feedback: "승인용 첨부 manifest를 잠그고 있습니다."
    };
    render();
    try {
      await currentClient.finalizeBatch(state.batchId);
      const manifest = await currentClient.lockBatch(state.batchId);
      if (sequence !== operationSequence) return null;
      state = {
        ...state,
        phase: "LOCKED",
        locked: true,
        manifest,
        items: state.items.map(item => ({
          ...item,
          status: "LOCKED",
          progress: 100
        })),
        feedback: "승인 요청에 첨부 manifest가 고정되었습니다."
      };
      render();
      return structuredClone(manifest);
    } catch (error) {
      if (expireIfNeeded(error)) return null;
      state = {
        ...state,
        phase: "FAILED",
        feedback: attachmentErrorMessage(error)
      };
      render();
      throw error;
    }
  };

  const beginNewApprovalVersion = () => {
    operationSequence += 1;
    batchPromise = null;
    state = createVoucherAttachmentUiState({
      approvalVersion: state.approvalVersion + 1,
      feedback: "새 승인 버전의 첨부 목록을 준비했습니다."
    });
    render();
  };

  container.addEventListener("click", event => {
    const select = event.target.closest("[data-voucher-attachment-select]");
    if (select) {
      container.querySelector("[data-voucher-attachment-input]")?.click();
      return;
    }
    const retry = event.target.closest("[data-voucher-attachment-retry]");
    if (retry) {
      void uploadItem(retry.dataset.voucherAttachmentRetry);
      return;
    }
    const remove = event.target.closest("[data-voucher-attachment-remove]");
    if (remove) {
      void removeItem(remove.dataset.voucherAttachmentRemove);
      return;
    }
    if (event.target.closest("[data-voucher-attachment-new-version]")) {
      beginNewApprovalVersion();
    }
  });
  container.addEventListener("change", event => {
    const input = event.target.closest("[data-voucher-attachment-input]");
    if (!input) return;
    void addFiles(input.files);
    input.value = "";
  });
  container.addEventListener("keydown", event => {
    const dropzone = event.target.closest("[data-voucher-attachment-dropzone]");
    if (!dropzone || !["Enter", " "].includes(event.key)) return;
    event.preventDefault();
    container.querySelector("[data-voucher-attachment-input]")?.click();
  });
  for (const eventName of ["dragenter", "dragover"]) {
    container.addEventListener(eventName, event => {
      const dropzone = event.target.closest("[data-voucher-attachment-dropzone]");
      if (!dropzone || state.locked) return;
      event.preventDefault();
      dropzone.dataset.dragActive = "true";
    });
  }
  container.addEventListener("dragleave", event => {
    const dropzone = event.target.closest("[data-voucher-attachment-dropzone]");
    if (dropzone) delete dropzone.dataset.dragActive;
  });
  container.addEventListener("drop", event => {
    const dropzone = event.target.closest("[data-voucher-attachment-dropzone]");
    if (!dropzone || state.locked) return;
    event.preventDefault();
    delete dropzone.dataset.dragActive;
    void addFiles(event.dataTransfer?.files);
  });

  render();
  return {
    addFiles,
    prepareForSubmission,
    beginNewApprovalVersion,
    clear() {
      operationSequence += 1;
      batchPromise = null;
      state = createVoucherAttachmentUiState();
      render();
    },
    setClient(nextClient) {
      currentClient = nextClient;
      render();
    },
    setContext(nextContext) {
      requestContext = nextContext;
    },
    getState() {
      return {
        ...state,
        manifest: state.manifest ? structuredClone(state.manifest) : null,
        items: state.items.map(({ file: _file, serverItem, ...item }) => ({
          ...item,
          serverItem: serverItem ? structuredClone(serverItem) : null
        }))
      };
    }
  };
}

export function createVoucherAttachmentUiState({
  approvalVersion = 1,
  feedback = "영수증, 계약서, 이미지, PDF 또는 ZIP 파일을 첨부할 수 있습니다."
} = {}) {
  return {
    ui_schema_version: AE_WEB_VOUCHER_ATTACHMENT_UI_SCHEMA_VERSION,
    phase: "IDLE",
    batchId: null,
    approvalVersion,
    locked: false,
    manifest: null,
    feedback,
    items: []
  };
}

export function renderVoucherAttachmentUi(state, client) {
  const disabled = state.locked || state.phase === "SUBMITTING";
  const totalBytes = state.items.reduce((total, item) => total + item.size, 0);
  return `
    <section
      class="voucher-attachment-composer"
      data-voucher-attachment-phase="${escapeAttribute(state.phase)}"
      data-voucher-attachment-locked="${state.locked ? "true" : "false"}"
      aria-label="전표 증빙 첨부"
    >
      <div class="voucher-attachment-heading">
        <div>
          <strong>증빙 첨부</strong>
          <span>${state.items.length}/20 · ${formatBytes(totalBytes)}</span>
        </div>
        <span class="voucher-attachment-version">승인 v${state.approvalVersion}</span>
      </div>
      <div
        class="voucher-attachment-dropzone"
        data-voucher-attachment-dropzone
        role="button"
        tabindex="${disabled ? "-1" : "0"}"
        aria-disabled="${disabled ? "true" : "false"}"
      >
        <input
          data-voucher-attachment-input
          type="file"
          multiple
          hidden
          ${disabled ? "disabled" : ""}
          accept="image/jpeg,image/png,image/webp,application/pdf,application/zip,application/x-zip-compressed,.docx,.xlsx,.pptx,.hwp"
        />
        <span>파일을 놓거나</span>
        <button type="button" data-voucher-attachment-select ${disabled ? "disabled" : ""}>파일 선택</button>
      </div>
      <p class="voucher-attachment-feedback" role="status" aria-live="polite">
        ${escapeHtml(state.feedback)}
      </p>
      ${renderItems(state, client)}
      ${
        state.locked
          ? `<button type="button" class="voucher-attachment-new-version" data-voucher-attachment-new-version>새 승인 버전</button>`
          : ""
      }
    </section>
  `;
}

function renderItems(state, client) {
  if (state.items.length === 0) return "";
  return `<ul class="voucher-attachment-list" aria-label="선택한 증빙 파일">
    ${state.items.map(item => renderItem(state, client, item)).join("")}
  </ul>`;
}

function renderItem(state, client, item) {
  const ready = ["READY", "LOCKED"].includes(item.status);
  const contentLinks =
    state.locked && ready && state.batchId
      ? `<span class="voucher-attachment-links">
          <a href="${escapeAttribute(
            client.contentRoute(state.batchId, item.attachmentId, { download: false })
          )}" target="_blank" rel="noopener">열기</a>
          <a href="${escapeAttribute(
            client.contentRoute(state.batchId, item.attachmentId, { download: true })
          )}">다운로드</a>
        </span>`
      : "";
  return `<li data-voucher-attachment-item="${escapeAttribute(item.localId)}" data-state="${escapeAttribute(item.status)}">
    <div class="voucher-attachment-file">
      <strong>${escapeHtml(item.name)}</strong>
      <span>${escapeHtml(item.type)} · ${formatBytes(item.size)}</span>
    </div>
    <div class="voucher-attachment-progress" aria-label="${escapeAttribute(
      `${item.name} ${item.progress}%`
    )}">
      <span style="width: ${item.progress}%"></span>
    </div>
    <span class="voucher-attachment-state">${statusLabel(item.status)}</span>
    ${item.error ? `<span class="voucher-attachment-error">${escapeHtml(item.error)}</span>` : ""}
    ${contentLinks}
    ${
      item.status === "FAILED" && !state.locked
        ? `<button type="button" data-voucher-attachment-retry="${escapeAttribute(item.localId)}">재시도</button>`
        : ""
    }
    ${
      !state.locked && item.status !== "UPLOADING"
        ? `<button type="button" class="quiet" data-voucher-attachment-remove="${escapeAttribute(item.localId)}" aria-label="${escapeAttribute(item.name)} 제거">제거</button>`
        : ""
    }
  </li>`;
}

function localItem(file) {
  return {
    localId: crypto.randomUUID(),
    attachmentId: crypto.randomUUID(),
    file,
    name: file.name,
    type: file.type,
    size: file.size,
    status: "QUEUED",
    progress: 0,
    error: null,
    serverItem: null
  };
}

function updateItem(state, localId, changes) {
  return {
    ...state,
    items: state.items.map(item =>
      item.localId === localId ? { ...item, ...changes } : item
    )
  };
}

function deriveReadyState(state) {
  if (state.items.length === 0) {
    return { ...state, phase: "IDLE" };
  }
  const statuses = new Set(state.items.map(item => item.status));
  if (statuses.has("FAILED")) return { ...state, phase: "FAILED" };
  if (statuses.has("QUEUED") || statuses.has("UPLOADING")) {
    return { ...state, phase: "UPLOADING" };
  }
  if ([...statuses].every(status => ACTIVE_ITEM_STATES.has(status))) {
    return {
      ...state,
      phase: "READY",
      feedback: `${state.items.length}개 파일이 승인 제출 준비를 마쳤습니다.`
    };
  }
  return state;
}

function resolveContext(context) {
  const value = typeof context === "function" ? context() : context;
  if (!value || typeof value !== "object") {
    throw new VoucherAttachmentClientError("첨부 요청 문맥이 없습니다.", {
      status: "VOUCHER_ATTACHMENT_CONTEXT_INVALID"
    });
  }
  return {
    conversationId: value.conversationId,
    interactionId: value.interactionId
  };
}

function statusLabel(status) {
  return {
    QUEUED: "대기",
    UPLOADING: "업로드 중",
    READY: "READY",
    FAILED: "실패",
    LOCKED: "승인 고정"
  }[status] || status;
}

function attachmentErrorMessage(error) {
  if (error instanceof VoucherAttachmentClientError) return error.message;
  return "첨부 요청을 처리하지 못했습니다.";
}

function formatBytes(value) {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function escapeAttribute(value) {
  return escapeHtml(value);
}
