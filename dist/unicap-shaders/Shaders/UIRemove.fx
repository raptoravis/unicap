#include "ReShade.fxh"

// Exported color texture — read by frame_capture addon to save BMP.
// In pre-UI mode (FC_PreUICapture=1), the addon reads directly from the
// backbuffer staging copy made before HUD draw calls, so this texture
// is only used as a fallback when pre-UI mode is off or unavailable.
texture UIRemove_ColorTex < pooled = false; >
{ Width = BUFFER_WIDTH; Height = BUFFER_HEIGHT; Format = RGBA8; };

float4 PS_Copy(float4 vpos : SV_Position, float2 uv : TEXCOORD) : SV_Target
{
    return tex2D(ReShade::BackBuffer, uv);
}

technique UIRemove
<
    enabled = 1;
    ui_label = "UI Remove (Capture Export)";
    ui_tooltip = "Snapshots backbuffer into UIRemove_ColorTex for the frame_capture addon. Must run after DepthToAddon.";
>
{
    pass ExportColor {
        VertexShader = PostProcessVS;
        PixelShader  = PS_Copy;
        RenderTarget = UIRemove_ColorTex;
    }
    pass RestoreBackBuffer {
        VertexShader = PostProcessVS;
        PixelShader  = PS_Copy;
    }
}
