<?php
        //include_once "Config.php";
        include_once "lib.php";
        include_once 'Excel/Classes/PHPExcel.php';

generateExcel($_GET['xml']);

function generateExcel($filename){
        

	$counter = 0;
	$file = "../".$filename;
	if($file!=NULL)
	{
	
	/** Error reporting */
		error_reporting(E_ALL);
		ini_set('display_errors', TRUE);
		ini_set('display_startup_errors', TRUE);
		date_default_timezone_set('Europe/London');
		
		if (PHP_SAPI == 'cli')
			die('This example should only be run from a Web Browser');

		/** Include PHPExcel */
		$objPHPExcel = new PHPExcel();
		$objPHPExcel->getProperties()->setCreator("Maarten Balliauw")
							 ->setLastModifiedBy("Maarten Balliauw")
							 ->setTitle("Office 2007 XLSX Test Document")
							 ->setSubject("Office 2007 XLSX Test Document")
							 ->setDescription("Test document for Office 2007 XLSX, generated using PHP classes.")
							 ->setKeywords("office 2007 openxml php")
							 ->setCategory("Test result file");
		
	
		$fil = file_get_contents($file);
		$xml = new SimpleXMLElement($fil);
		$tab = $xml->page->tab;
                $colmnLetter= new excelCell();
                
                $tablname =  getTableNamebyDocLink($filename);
                sql_login();
                $objPHPExcel->setActiveSheetIndex(0);
                for ($i =0;$i<count($tab);$i++){
                 $objPHPExcel->setActiveSheetIndex(0)->setCellValue($colmnLetter->next()."1",$tab[$i]->dataname);
                }
                
            
                
 
                $qeury = "select * from ".$tablname;
                $result = mysql_query($qeury);
                      if(!$result) {
                             echo "Query failed\n<br><b>$qeury</b>\n";
                             echo mysql_error(); // (Is that not the name)
                        }
                      $rowCount = 2;
                 while( $row = mysql_fetch_array($result)){
                     $colmnLetter->reset();
                    for ($i =0;$i<count($tab);$i++){
                         $objPHPExcel->setActiveSheetIndex(0)->setCellValue($colmnLetter->next().$rowCount,$row[$i]);
                    }
                    $rowCount++;
                }
                $objPHPExcel->getActiveSheet()->setTitle("sample");
                // Set active sheet index to the first sheet, so Excel opens this as the first sheet
                $objPHPExcel->setActiveSheetIndex(0);
                // Redirect output to a client’s web browser (Excel2007)
                header('Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet');
                header('Content-Disposition: attachment;filename="'.$xml->title.'.xlsx"');
                header('Cache-Control: max-age=0');

                $objWriter = PHPExcel_IOFactory::createWriter($objPHPExcel, 'Excel2007');
                $objWriter->save('php://output');
        }          
        else {
        echo " Form is not found, or you do not have the permission to check out! ";
        }
}
?>