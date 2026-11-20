import { afterEach, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import ScoreChart, { type ChartPoint } from './ScoreChart'

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals() })
it('keeps curves and usual bands inside resolved segments on a mobile chart', () => {
  vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(320)
  vi.stubGlobal('matchMedia', () => ({ matches: true }))
  const points: ChartPoint[] = [0, 1, 2, 3].map(i => ({ key: i, segment: i < 2 ? 1 : 2, highlight: i >= 2, occurredAt: i * 1000 + 1000, month: '2026-01', monthLabel: 'Jan', value: i < 2 ? 7 : 0, band: i < 2 ? 'G' : 'F', curveMedian: i < 2 ? 7 : 0, curveQ1: i < 2 ? 6 : 0, curveQ3: i < 2 ? 8 : 1 }))
  const select = vi.fn()
  const { container } = render(<ScoreChart points={points} smoothing={3} selected={0} onSelect={select} label="Technique ratings" boundary={{ start: 0, end: 5000, uncertainUntil: 500 }} markers={[{ at: 2000 }, { at: 3000 }]} />)
  expect(container.querySelector('.ca-medline')?.getAttribute('d')?.match(/M/g)).toHaveLength(2)
  expect(container.querySelector('.ca-band')?.getAttribute('d')?.match(/M/g)).toHaveLength(2)
  expect(container.querySelector('pattern')).toBeInTheDocument()
  expect(container.querySelector('rect[fill-opacity=".08"]')).toBeInTheDocument()
  fireEvent.keyDown(screen.getByRole('group', { name: /Technique ratings/ }), { key: 'ArrowRight' })
  expect(select).toHaveBeenCalledWith(1)
})
it('keeps date positions stable when a technique period is selected',()=>{
 vi.stubGlobal('matchMedia', () => ({ matches:true }))
 vi.spyOn(HTMLElement.prototype,'clientWidth','get').mockReturnValue(320)
 const points:ChartPoint[]=[0,1,2,3].map(i=>({key:i,occurredAt:1000+i*1000,month:'2026-01',monthLabel:'Jan',value:7,band:'G'}))
 const props={points,smoothing:3,selected:null,onSelect:vi.fn(),label:'Technique ratings',timeScale:true,selectionMode:'tap' as const}
 const view=render(<ScoreChart {...props}/>);const before=[...view.container.querySelectorAll('.ca-score-point')].map(e=>e.getAttribute('cx'))
 view.rerender(<ScoreChart {...props} boundary={{start:3000,end:4000}}/>)
 expect([...view.container.querySelectorAll('.ca-score-point')].map(e=>e.getAttribute('cx'))).toEqual(before)
 expect(new Set(before).size).toBe(4)
})
it('uses calendar ticks and the saved date range across pages of a period', () => {
  vi.stubGlobal('matchMedia', () => ({ matches: true }))
  vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(560)
  const period = { start: Date.UTC(2025, 11, 1), end: Date.UTC(2026, 3, 1) }
  const point = (key: number, occurredAt: number): ChartPoint =>
    ({ key, occurredAt, month: '', monthLabel: '', value: 7, band: 'G' })
  const first = point(1, Date.UTC(2025, 11, 5)), later = point(2, Date.UTC(2026, 1, 17))
  const props = { smoothing: 3, selected: null, onSelect: vi.fn(), label: 'Technique ratings', timeScale: true, timeDomain: period, boundary: period }
  const view = render(<ScoreChart {...props} points={[first, later]} />)
  const labels = () => [...view.container.querySelectorAll('text.ca-axis')].slice(5).map(node => node.textContent)
  const ticks = labels()
  const laterX = view.container.querySelectorAll('.ca-score-point')[1].getAttribute('cx')
  const endX = view.container.querySelectorAll('.ca-selection-edge')[1].getAttribute('x1')
  expect(ticks).toEqual(['Dec 25', 'Jan 26', 'Feb 26', 'Mar 26', 'Apr 26'])
  expect(Number(laterX)).toBeLessThan(Number(endX))
  view.rerender(<ScoreChart {...props} points={[later]} />)
  expect(labels()).toEqual(ticks)
  expect(view.container.querySelector('.ca-score-point')?.getAttribute('cx')).toBe(laterX)
})
it('shades a period continuing through the viewport without drawing fake endpoints', () => {
  vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(320)
  const { container } = render(<ScoreChart points={[]} smoothing={3} selected={null} label="Technique ratings"
    timeScale timeDomain={{ start: 2000, end: 3000 }} boundary={{ start: 1000, end: 4000 }} />)
  expect(container.querySelector('.ca-selection-band')).toBeInTheDocument()
  expect(container.querySelectorAll('.ca-selection-edge')).toHaveLength(0)
})
it('ignores vertical scrolling and only selects a period after a tap ends',()=>{
 vi.stubGlobal('matchMedia', () => ({ matches:true }))
 vi.spyOn(HTMLElement.prototype,'clientWidth','get').mockReturnValue(320)
 vi.spyOn(HTMLElement.prototype,'getBoundingClientRect').mockReturnValue({left:0,width:320,top:0,height:200,right:320,bottom:200,x:0,y:0,toJSON:()=>({})})
 vi.stubGlobal('PointerEvent',MouseEvent)
 const select=vi.fn();const points:ChartPoint[]=[0,1].map(i=>({key:i,occurredAt:1000+i*1000,month:'2026-01',monthLabel:'Jan',value:7,band:'G'}))
 render(<ScoreChart points={points} smoothing={3} selected={null} onSelect={select} label="Tap chart" timeScale selectionMode="tap"/>);
 const chart=screen.getByRole('group',{name:/Tap chart/})
 fireEvent.pointerDown(chart,{clientX:150,clientY:50});expect(select).not.toHaveBeenCalled()
 fireEvent.pointerMove(chart,{clientX:151,clientY:100});fireEvent.pointerUp(chart,{clientX:151,clientY:100});expect(select).not.toHaveBeenCalled()
 fireEvent.pointerDown(chart,{clientX:300,clientY:50});fireEvent.pointerUp(chart,{clientX:300,clientY:50});expect(select).toHaveBeenCalledWith(1)
})
