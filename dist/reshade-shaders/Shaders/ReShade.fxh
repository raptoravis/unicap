// Minimal ReShade.fxh for unicap capture pipeline
// Provides the standard bindings and macros required by DepthToAddon.fx and UIRemove.fx.
// The numeric macros (BUFFER_WIDTH, BUFFER_HEIGHT, RESHADE_DEPTH_*) are injected by the
// ReShade runtime preprocessor; this file only provides the #define wrappers and declarations.

#pragma once

// ── Buffer dimension helpers ─────────────────────────────────────────────────
// ReShade 5.9.2 already defines BUFFER_RCP_WIDTH/HEIGHT/PIXEL_SIZE as derived
// preprocessor macros at runtime, so guard our fallbacks to avoid redefinition.

#ifndef BUFFER_RCP_WIDTH
  #define BUFFER_RCP_WIDTH  (1.0 / BUFFER_WIDTH)
#endif
#ifndef BUFFER_RCP_HEIGHT
  #define BUFFER_RCP_HEIGHT (1.0 / BUFFER_HEIGHT)
#endif
#ifndef BUFFER_PIXEL_SIZE
  #define BUFFER_PIXEL_SIZE float2(BUFFER_RCP_WIDTH, BUFFER_RCP_HEIGHT)
#endif

// ── Depth preprocessing defaults (overridden by ReShade settings) ────────────

#ifndef RESHADE_DEPTH_INPUT_IS_UPSIDE_DOWN
  #define RESHADE_DEPTH_INPUT_IS_UPSIDE_DOWN 0
#endif
#ifndef RESHADE_DEPTH_INPUT_IS_REVERSED
  #define RESHADE_DEPTH_INPUT_IS_REVERSED 1
#endif
#ifndef RESHADE_DEPTH_INPUT_IS_LOGARITHMIC
  #define RESHADE_DEPTH_INPUT_IS_LOGARITHMIC 0
#endif
#ifndef RESHADE_DEPTH_INPUT_X_SCALE
  #define RESHADE_DEPTH_INPUT_X_SCALE 1
#endif
#ifndef RESHADE_DEPTH_INPUT_Y_SCALE
  #define RESHADE_DEPTH_INPUT_Y_SCALE 1
#endif
#ifndef RESHADE_DEPTH_INPUT_X_PIXEL_OFFSET
  #define RESHADE_DEPTH_INPUT_X_PIXEL_OFFSET 0
#endif
#ifndef RESHADE_DEPTH_INPUT_Y_PIXEL_OFFSET
  #define RESHADE_DEPTH_INPUT_Y_PIXEL_OFFSET 0
#endif
#ifndef RESHADE_DEPTH_LINEARIZATION_FAR_PLANE
  #define RESHADE_DEPTH_LINEARIZATION_FAR_PLANE 1000.0
#endif
#ifndef RESHADE_DEPTH_MULTIPLIER
  #define RESHADE_DEPTH_MULTIPLIER 1
#endif

// ── Standard texture bindings ─────────────────────────────────────────────────

namespace ReShade
{
	texture BackBufferTex : COLOR;
	sampler BackBuffer
	{
		Texture = BackBufferTex;
		AddressU = Clamp;
		AddressV = Clamp;
	};

	texture DepthBufferTex : DEPTH;
	sampler DepthBuffer
	{
		Texture = DepthBufferTex;
		AddressU = Clamp;
		AddressV = Clamp;
	};
}

// ── Full-screen vertex shader ─────────────────────────────────────────────────

void PostProcessVS(in uint id : SV_VertexID,
                   out float4 position : SV_Position,
                   out float2 texcoord : TEXCOORD0)
{
	texcoord.x = (id == 2) ? 2.0 : 0.0;
	texcoord.y = (id == 1) ? 2.0 : 0.0;
	position   = float4(texcoord * float2(2.0, -2.0) + float2(-1.0, 1.0), 0.0, 1.0);
}
