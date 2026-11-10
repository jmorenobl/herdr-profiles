// gpui-kit / gpui-base stand-in: the builders aren't used by the functions under test.
const nothing = () => { throw new Error("UI is not available in tests"); };
export const div = nothing, h_flex = nothing, v_flex = nothing;
export const Input = nothing, Textarea = nothing, TextView = nothing;
export const InputState = { new: nothing }, TextareaState = { new: nothing };
