/**
 * avatarLifecycle.js - 3D Avatar Rendering Lifecycle and State Helpers
 *
 * Provides pure lifecycle state helpers for:
 * - Collapsible 3D avatar controls and unmounting
 * - WebGL render loop suspension when document is hidden
 * - Context loss handling, restoration listeners, and resource cleanup
 * - WebGL availability detection
 *
 * Note: Metric calculations are handled exclusively by liveDisplayHelper.js.
 * 2D image-plane angles are never equated with measured 3D physical depth.
 */

export const AVATAR_REQUIRED_DISCLAIMER =
  '3D Digital Twin · Model-derived avatar (derived/2D/unverified); muscle activity NOT MEASURED · Drag to rotate · Scroll to zoom';

export const AVATAR_COLLAPSED_NOTICE =
  '3D Digital Twin collapsed to preserve resources · Model-derived avatar (derived/2D/unverified); muscle activity NOT MEASURED';

export const AVATAR_CONTEXT_LOST_NOTICE =
  'WebGL context lost. Rendering suspended to protect GPU resources · Model-derived avatar (derived/2D/unverified); muscle activity NOT MEASURED';

export const AVATAR_UNAVAILABLE_2D_NOTICE =
  '3D motion UNAVAILABLE — camera inference provides 2D points without measured depth.';

export const AVATAR_UNAVAILABLE_WEBGL_NOTICE =
  '3D Viewport unavailable (WebGL unsupported or disabled) · Model-derived avatar (derived/2D/unverified); muscle activity NOT MEASURED';

export const AVATAR_UNMEASURED_KINEMATICS_NOTICE =
  'Kinematics unmeasured · Model-derived avatar (derived/2D/unverified); muscle activity NOT MEASURED';

export const AVATAR_STATUS = {
  ACTIVE: 'ACTIVE',
  COLLAPSED: 'COLLAPSED',
  SUSPENDED_HIDDEN: 'SUSPENDED_HIDDEN',
  CONTEXT_LOST: 'CONTEXT_LOST',
  UNAVAILABLE_2D: 'UNAVAILABLE_2D',
  UNAVAILABLE_WEBGL: 'UNAVAILABLE_WEBGL',
  UNMEASURED_KINEMATICS: 'UNMEASURED_KINEMATICS',
};

/**
 * Checks if WebGL is supported in the current environment.
 */
export function isWebGLSupported() {
  if (typeof window === 'undefined') return true;
  try {
    const canvas = document.createElement('canvas');
    return Boolean(
      window.WebGLRenderingContext &&
      (canvas.getContext('webgl2') || canvas.getContext('webgl') || canvas.getContext('experimental-webgl'))
    );
  } catch {
    return false;
  }
}

/**
 * Determines if the 3D Digital Twin component should be mounted.
 * When collapsed or when WebGL is unsupported, returns false so the component
 * and its WebGL canvas/RAF are completely torn down from the DOM.
 */
export function shouldMountAvatar({
  avatarVisible = true,
  isSimulated = false,
  demoMode = false,
  webglSupported = true,
} = {}) {
  if (!avatarVisible) return false;
  if (!webglSupported) return false;
  return Boolean(isSimulated || demoMode);
}

/**
 * Checks if the WebGL animation frame / render loop should be suspended.
 * Suspended whenever document is hidden, avatar is collapsed, or context is lost.
 */
export function isRenderLoopSuspended({
  documentHidden = false,
  avatarVisible = true,
  contextLost = false,
} = {}) {
  if (!avatarVisible) return true;
  if (documentHidden) return true;
  if (contextLost) return true;
  return false;
}

/**
 * Computes the complete avatar lifecycle state.
 *
 * Notice: When context is lost, the Canvas remains mounted (shouldRenderCanvas: true)
 * in a suspended state (frameloop: 'never') with an overlay notice and a 'Restore 3D View'
 * action, so the browser webglcontextrestored event or user restore can recover rendering.
 */
export function getAvatarLifecycleState({
  avatarVisible = true,
  isSimulated = false,
  demoMode = false,
  documentHidden = false,
  contextLost = false,
  webglSupported = true,
  kinematicsMissing = false,
} = {}) {
  if (!avatarVisible) {
    return {
      status: AVATAR_STATUS.COLLAPSED,
      isMounted: false,
      shouldRenderCanvas: false,
      frameloop: 'never',
      placeholderText: AVATAR_COLLAPSED_NOTICE,
      hasRestoreButton: false,
      unmeasuredNotice: AVATAR_COLLAPSED_NOTICE,
    };
  }

  if (!webglSupported) {
    return {
      status: AVATAR_STATUS.UNAVAILABLE_WEBGL,
      isMounted: false,
      shouldRenderCanvas: false,
      frameloop: 'never',
      placeholderText: AVATAR_UNAVAILABLE_WEBGL_NOTICE,
      hasRestoreButton: false,
      unmeasuredNotice: AVATAR_UNAVAILABLE_WEBGL_NOTICE,
    };
  }

  if (!isSimulated && !demoMode) {
    return {
      status: AVATAR_STATUS.UNAVAILABLE_2D,
      isMounted: false,
      shouldRenderCanvas: false,
      frameloop: 'never',
      placeholderText: AVATAR_UNAVAILABLE_2D_NOTICE,
      hasRestoreButton: false,
      unmeasuredNotice: AVATAR_UNAVAILABLE_2D_NOTICE,
    };
  }

  if (contextLost) {
    return {
      status: AVATAR_STATUS.CONTEXT_LOST,
      isMounted: true,
      shouldRenderCanvas: true, // Keep Canvas mounted in suspended state to allow webglcontextrestored
      frameloop: 'never',
      placeholderText: AVATAR_CONTEXT_LOST_NOTICE,
      hasRestoreButton: true,
      unmeasuredNotice: AVATAR_CONTEXT_LOST_NOTICE,
    };
  }

  if (documentHidden) {
    return {
      status: AVATAR_STATUS.SUSPENDED_HIDDEN,
      isMounted: true,
      shouldRenderCanvas: true,
      frameloop: 'never',
      placeholderText: null,
      hasRestoreButton: false,
      unmeasuredNotice: null,
    };
  }

  if (kinematicsMissing) {
    return {
      status: AVATAR_STATUS.UNMEASURED_KINEMATICS,
      isMounted: true,
      shouldRenderCanvas: true,
      frameloop: 'always',
      placeholderText: null,
      hasRestoreButton: false,
      unmeasuredNotice: AVATAR_UNMEASURED_KINEMATICS_NOTICE,
    };
  }

  return {
    status: AVATAR_STATUS.ACTIVE,
    isMounted: true,
    shouldRenderCanvas: true,
    frameloop: 'always',
    placeholderText: null,
    hasRestoreButton: false,
    unmeasuredNotice: null,
  };
}

/**
 * Creates WebGL context loss and restoration handlers with event.preventDefault()
 * to protect GPU resources and allow graceful context recovery.
 */
export function createContextLossManager({ onContextLost, onContextRestored } = {}) {
  let isLost = false;

  const handleContextLost = (event) => {
    if (event && typeof event.preventDefault === 'function') {
      event.preventDefault();
    }
    isLost = true;
    onContextLost?.(event);
  };

  const handleContextRestored = (event) => {
    isLost = false;
    onContextRestored?.(event);
  };

  return {
    isContextLost: () => isLost,
    handleContextLost,
    handleContextRestored,
  };
}
