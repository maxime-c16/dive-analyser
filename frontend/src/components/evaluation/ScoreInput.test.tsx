import i18n from '../../i18n'
import { useState } from 'react'
import { act, fireEvent, render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'
import ScoreInput from './ScoreInput'
it('has no default vote, accepts zero and keeps half points within the score scale', () => {
  function Harness() { const [score, setScore] = useState<number | null>(null); return <ScoreInput score={score} disabled={false} onScore={setScore} /> }
  render(<Harness />)
  const half = screen.getByRole('button', { name: '+ ½' })
  expect(half).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: '0 out of 10' }))
  expect(screen.getByRole('img', { name: '0.0 out of 10' })).toBeInTheDocument()
  fireEvent.click(half)
  expect(screen.getByRole('img', { name: '0.5 out of 10' })).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: '7 out of 10' }))
  expect(screen.getByRole('img', { name: '7.5 out of 10' })).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: '10 out of 10' }))
  expect(half).toBeDisabled()
  expect(screen.getByRole('img', { name: '10.0 out of 10' })).toBeInTheDocument()
})

it('formats French half-point scores and switches language without changing the selected score', async () => {
  await act(async () => { await i18n.changeLanguage('fr') })
  try {
    function Harness() { const [score, setScore] = useState<number | null>(13); return <ScoreInput score={score} disabled={false} onScore={setScore} /> }
    render(<Harness />)
    expect(screen.getByRole('img', { name: '6,5 sur 10' })).toBeInTheDocument()
    expect(screen.getByText('6,5 / 10')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '+ ½' }))
    expect(screen.getByRole('img', { name: '6,0 sur 10' })).toBeInTheDocument()
    await act(async () => { await i18n.changeLanguage('en') })
    expect(screen.getByRole('img', { name: '6.0 out of 10' })).toBeInTheDocument()
  } finally { await act(async () => { await i18n.changeLanguage('en') }) }
})
