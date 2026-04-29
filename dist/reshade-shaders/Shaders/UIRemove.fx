// UIRemove.fx
// 将深度缓冲为 0 的像素（UI/HUD，无深度写入）替换为纯黑，在帧捕获前生效。
//
// 适用条件：UE4/UE5 Reverse-Z（clear value = 0.0）
// 真实场景几何体深度约 0.02–1.0，UI 恒为 0.0，阈值 0.001 安全。
//
// 部署步骤：
//   1. 将此文件放入 reshade-shaders/Shaders/
//   2. ReShade 主界面勾选 UIRemove 技术
//   3. 确保它排在 Frame Capture 触发之前（在 ReShade 效果列表中拖到靠前位置）
//
// 可调参数（preprocessor definitions）：
//   UI_DEPTH_THRESHOLD  默认 0.001

#include "ReShade.fxh"

#ifndef UI_DEPTH_THRESHOLD
  #define UI_DEPTH_THRESHOLD 0.001
#endif

float4 PS_RemoveUI(float4 vpos : SV_Position, float2 uv : TEXCOORD) : SV_Target
{
    // 读取 ReShade::BackBuffer —— 这是所有效果开始前的后备缓冲副本（原始游戏画面）。
    // 写入实际后备缓冲，撤销 DepthToAddon 等可能对后备缓冲造成的污染。
    // 注意：此处故意不做深度检测，避免深度缓冲不可用时画面全黑。
    return tex2D(ReShade::BackBuffer, uv);
}

technique UIRemove
<
    enabled = 1;
    ui_label = "UI Remove (FF7 Capture)";
    ui_tooltip = "Blacks out UI/HUD pixels before frame capture. UE4 Reverse-Z only.\n"
                 "pack_hdf5.py applies the same mask as a fallback if this is disabled.";
>
{
    pass
    {
        VertexShader = PostProcessVS;
        PixelShader  = PS_RemoveUI;
    }
}
