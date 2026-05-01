// CaptureStatus.fx — small always-on status indicator driven by the addon.
//
// The frame_capture addon writes the high-level state (idle / surveying /
// capturing) every frame via reshade::api::effect_runtime::set_uniform_value
// into Status_State. This shader draws a small colored bar in the top-right
// corner of the displayed backbuffer (it does NOT affect the captured BMP
// because pre-UI capture happens before any ReShade effect runs).
//
// State encoding:
//   0 = idle      (no draw)
//   1 = surveying (blue)
//   2 = capturing (red)

#include "ReShade.fxh"

uniform int Status_State <
    ui_label = "Capture state";
    ui_type  = "combo";
    ui_items = "Idle\0Surveying\0Capturing\0";
> = 0;

float4 PS_Status(float4 vpos : SV_Position, float2 uv : TEXCOORD) : SV_Target
{
    float4 col = tex2D(ReShade::BackBuffer, uv);
    if (Status_State == 0) return col;

    // 顶部居中横条：宽 240px，高 14px，距顶 16px
    const float bar_w = 240.0;
    const float bar_h = 14.0;
    const float pad_top = 16.0;
    float2 origin = float2((BUFFER_WIDTH - bar_w) * 0.5, pad_top);
    float2 px = vpos.xy;

    bool inside = px.x >= origin.x && px.x < origin.x + bar_w
               && px.y >= origin.y && px.y < origin.y + bar_h;
    if (!inside) return col;

    float4 c_survey  = float4(0.20, 0.55, 1.00, 1.0);   // 蓝
    float4 c_capture = float4(1.00, 0.30, 0.30, 1.0);   // 红
    float4 indicator = (Status_State == 1) ? c_survey : c_capture;

    // 1px 边框
    bool border = px.x < origin.x + 1.0 || px.x >= origin.x + bar_w - 1.0
               || px.y < origin.y + 1.0 || px.y >= origin.y + bar_h - 1.0;
    return border ? float4(0.0, 0.0, 0.0, 1.0) : indicator;
}

technique CaptureStatus <
    enabled = 1;
    ui_label = "Capture status indicator";
    ui_tooltip = "Driven by the unicap addon — do not toggle manually.";
>
{
    pass {
        VertexShader = PostProcessVS;
        PixelShader  = PS_Status;
    }
}
