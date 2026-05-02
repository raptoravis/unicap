#include "ReShade.fxh"

// Snapshots the (post-UI) BackBuffer into a named texture so the
// frame_capture addon can read it via runtime->enumerate_texture_variables.
//
// NOT a UI-removal shader — this is a passthrough copy. Despite the legacy
// name (was UIRemove.fx), it does not mask anything. Discriminating UI
// pixels would require a different shader using depth or alpha.
//
// In pre-UI mode (FC_PreUICapture=1) the addon ignores this texture and
// reads directly from the GPU staging copy made before HUD draws. This
// texture is the fallback path for post-UI capture / "both" mode.
texture BackBufferExport_ColorTex < pooled = false; >
{ Width = BUFFER_WIDTH; Height = BUFFER_HEIGHT; Format = RGBA8; };

float4 PS_Copy(float4 vpos : SV_Position, float2 uv : TEXCOORD) : SV_Target
{
    return tex2D(ReShade::BackBuffer, uv);
}

technique BackBufferExport
<
    enabled = 1;
    ui_label = "BackBuffer Export (Capture)";
    ui_tooltip = "Copies BackBuffer into BackBufferExport_ColorTex for the frame_capture addon. Must run after DepthToAddon.";
>
{
    pass ExportColor {
        VertexShader = PostProcessVS;
        PixelShader  = PS_Copy;
        RenderTarget = BackBufferExport_ColorTex;
    }
    pass RestoreBackBuffer {
        VertexShader = PostProcessVS;
        PixelShader  = PS_Copy;
    }
}
