import './style.css';
export const metadata = {
    title:'Parking Smart | Dashboard',
    description:'Monitoreo IoT de estacionamientos'
};

export default function RootLayout({children}:{children:React.ReactNode}) {return <html lang="es"><body>{children}</body></html>}
