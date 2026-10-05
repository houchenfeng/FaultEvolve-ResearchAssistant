import { Link } from '@tanstack/react-router';

/** 404：路由不存在时给出可执行的下一步，而不是空白页。 */
export function NotFoundPage() {
  return (
    <div className="grid h-full place-items-center p-6">
      <div className="max-w-md text-center">
        <p className="text-sm font-medium text-fg">页面不存在</p>
        <p className="mt-1 text-xs text-fg-muted">
          该地址没有对应的页面。侧栏固定只有四个模块，其余视图都是运行内部的深链接。
        </p>
        <Link to="/" className="mt-3 inline-block text-xs text-brand-600 hover:underline">
          ← 返回总览
        </Link>
      </div>
    </div>
  );
}
