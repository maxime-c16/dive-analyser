import { act, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { useRef } from 'react'
import { useBottomNotice } from './useBottomNotice'
import { useBottomAction } from './useMobileNavigation'
function Notice({id}:{id:string}) {
  const ref=useRef<HTMLDivElement>(null),show=useBottomNotice(ref,true)
  return show ? <div ref={ref} data-testid={id}>Notice</div> : null
}
function View({dirty=false,second=false}:{dirty?:boolean;second?:boolean}) {
  useBottomAction(dirty)
  return <><Notice id="one" />{second&&<Notice id="two" />}</>
}
afterEach(()=>{vi.restoreAllMocks();vi.unstubAllGlobals()})
it('reserves and stacks mobile notices, releases on hide/unmount, and leaves desktop at zero',()=>{
  vi.stubGlobal('innerWidth',390)
  vi.stubGlobal('ResizeObserver',class { observe(){} disconnect(){} })
  vi.spyOn(HTMLElement.prototype,'getBoundingClientRect').mockReturnValue({height:100} as DOMRect)
  const view=render(<View second />)
  expect(document.documentElement.style.getPropertyValue('--mobile-notice-offset')).toBe('240px')
  expect(screen.getByTestId('two').style.getPropertyValue('--mobile-notice-before')).toBe('108px')
  view.rerender(<View dirty second />);expect(screen.queryByTestId('one')).not.toBeInTheDocument();expect(document.documentElement.style.getPropertyValue('--mobile-notice-offset')).toBe('0px')
  view.rerender(<View />);expect(screen.getByTestId('one')).toBeInTheDocument()
  vi.stubGlobal('innerWidth',1440);act(()=>window.dispatchEvent(new Event('resize')))
  expect(document.documentElement.style.getPropertyValue('--mobile-notice-offset')).toBe('0px')
  view.unmount()
})
