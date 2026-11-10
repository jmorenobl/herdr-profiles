// gpui-kit / gpui-base stand-in that lets the ideas views render under node: every builder is
// a chain that takes any call and returns itself (`when` runs its branch, so its code runs too).
// Nothing is drawn; rendering only shows that a view's code runs without throwing.
const chain = new Proxy(function () {}, {
  get(_t, name) {
    if (name === "when") return (cond, f) => (cond ? f(chain) : chain);
    if (name === "then") return undefined;      // not a promise
    return () => chain;
  },
  apply() { return chain; },
});
const builder = () => chain;
export const div = builder, h_flex = builder, v_flex = builder;
export const Input = { new: builder }, Textarea = { new: builder }, TextView = { markdown: builder };

function textState() {
  let value = "";
  return { value: () => value, set_value(v) { value = v; }, on() {}, focus() {}, set_auto_grow() {} };
}
export const InputState = { new: textState }, TextareaState = { new: textState };

export class View {}
