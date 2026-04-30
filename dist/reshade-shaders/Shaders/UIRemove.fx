#include "ReShade.fxh"

texture UIRemove_ColorTex < pooled = false; >
{ Width = BUFFER_WIDTH; Height = BUFFER_HEIGHT; Format = RGBA8; };

float4 PS_Copy(float4 vpos : SV_Position, float2 uv : TEXCOORD) : SV_Target
{
    return tex2D(ReShade::BackBuffer, uv);
}

technique UIRemove
<
    enabled = 1;
    ui_label = "UI Remove (FF7 Capture)";
    ui_tooltip = "Restores backbuffer for clean capture. Must run after DepthToAddon.";
>
{
    // Pass 1: snapshot BackBuffer into UIRemove_ColorTex (read by frame_capture addon)
    pass ExportColor {
        VertexShader = PostProcessVS;
        PixelShader  = PS_Copy;
        RenderTarget = UIRemove_ColorTex;
    }
    // Pass 2: write same BackBuffer content back to swap chain (restore for capture_screenshot fallback)
    pass RestoreBackBuffer {
        VertexShader = PostProcessVS;
        PixelShader  = PS_Copy;
    }
}
