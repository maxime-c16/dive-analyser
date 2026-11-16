import {render,screen,fireEvent} from '@testing-library/react'
import {expect,it,vi} from 'vitest'
import ClipFilmstrip from './ClipFilmstrip'
import '../../i18n'
vi.mock('../DiveThumbnail',()=>({default:()=> <span>Thumbnail</span>}))
const attempts=[1,2,3,4].map((id)=>({id,dive_code:'5122D',dive_datetime:`2026-04-${id<3?'21':'28'}T10:0${id}:00`,performance:'G',height:'1m'})) as any
it('browses clips across sessions in technique history and exposes the remaining history',()=>{
 const next=vi.fn(),select=vi.fn()
 render(<ClipFilmstrip attempt={attempts[0]} attempts={attempts} onSelect={select} history={{total:107,previous:false,next:true,loading:false,onPrevious:vi.fn(),onNext:next}} />)
 expect(screen.getAllByText('Thumbnail')).toHaveLength(4)
 expect(screen.getByText('4 / 107 clips loaded')).toBeInTheDocument()
 fireEvent.click(screen.getByRole('button',{name:'28 Apr 2026 · 10:04'}));expect(select).toHaveBeenCalledWith(attempts[3])
 fireEvent.click(screen.getByRole('button',{name:'Load more clips'}));expect(next).toHaveBeenCalledOnce()
})
it('keeps the ordinary Library filmstrip scoped to the same day',()=>{
 render(<ClipFilmstrip attempt={attempts[0]} attempts={attempts} onSelect={vi.fn()}/>);
 expect(screen.getAllByText('Thumbnail')).toHaveLength(2)
})
it('distinguishes same-time clips by their ordinal in a selected session',()=>{
 render(<ClipFilmstrip attempt={attempts[0]} attempts={attempts.slice(0,2)} onSelect={vi.fn()} history={{sessionLabel:'21 Apr 2026',total:2,previous:false,next:false,loading:false,onPrevious:vi.fn(),onNext:vi.fn()}} />)
 expect(screen.getByText('Dive 1')).toBeInTheDocument()
 expect(screen.getByText('Dive 2')).toBeInTheDocument()
 expect(screen.getByRole('button',{name:/Dive 2/})).toHaveAccessibleName('21 Apr 2026 · 10:02 · Dive 2')
})
