import React from 'react'
import { useParams } from 'react-router-dom'
import SchemaForm from '../components/SchemaForm'

export default function SchemaFormPage() {
  const params = useParams()
  const name = params.name || 'inventory_item'
  return (
    <div>
      <h2 className="text-xl font-semibold mb-4">Schema Form: {name}</h2>
      <SchemaForm name={name} />
    </div>
  )
}
