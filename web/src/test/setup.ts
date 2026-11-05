/**
 * 测试环境准备。
 *
 * React Flow 依赖真实尺寸做两件事：可见区域裁剪（`onlyRenderVisibleElements`）
 * 与坐标变换。jsdom 里所有元素的尺寸都是 0，缺了这几个 mock 的话
 * **节点会在测试里凭空消失**（裁剪认为它们全在视口外）——
 * 这个坑排查起来很费时间，所以在此统一补上。
 */
import '@testing-library/jest-dom/vitest';
import { vi } from 'vitest';

class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}

vi.stubGlobal('ResizeObserver', ResizeObserverStub);

const SIZE = { width: 1200, height: 800 };

vi.spyOn(HTMLElement.prototype, 'offsetWidth', 'get').mockReturnValue(SIZE.width);
vi.spyOn(HTMLElement.prototype, 'offsetHeight', 'get').mockReturnValue(SIZE.height);
vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(SIZE.width);
vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockReturnValue(SIZE.height);

vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({
  x: 0,
  y: 0,
  width: SIZE.width,
  height: SIZE.height,
  top: 0,
  left: 0,
  right: SIZE.width,
  bottom: SIZE.height,
  toJSON: () => ({}),
});

// jsdom 未实现 matchMedia，React Flow 的主题检测会调用它。
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  }),
});

if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = () => {};
}
