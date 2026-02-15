import { noop } from "./actions";
import Index, { getStaticProps } from "../pages/index.jsx";

/**
 * App Router 根页面：复用 Pages Router 首页的组件与数据，仅在此挂载 Server Action
 * 以便在「项目本身的首页」上复现 React2Shell（POST / 走 RSC 解码）。
 */
export default async function RootPage() {
  const { props } = await getStaticProps();
  return (
    <>
      <form action={noop} style={{ display: "none" }} aria-hidden="true">
        <button type="submit" />
      </form>
      <Index {...props} />
    </>
  );
}
